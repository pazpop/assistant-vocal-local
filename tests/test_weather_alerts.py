"""Tests pour weather_alerts.py : parsing du flux Atom, déclenchement de
l'annonce proactive et période silencieuse, sans appel réseau réel
(requests.get est mocké)."""
from datetime import time as heure
from unittest.mock import MagicMock, patch

from weather_alerts import AlertesMeteoClient, _dans_la_periode_silencieuse, demande_alerte

FLUX_SANS_ALERTE = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Aucune alerte en vigueur, secteur de Montreal</title>
    <summary type="html">Aucune alerte en vigueur.</summary>
    <id>tag:meteo.gc.ca,2013-04-16:20260903031620</id>
  </entry>
</feed>
"""

FLUX_AVEC_ALERTE = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Avertissement de froid extreme en vigueur, secteur de Montreal</title>
    <summary type="html">&lt;b&gt;Avertissement&lt;/b&gt; de froid extreme.</summary>
    <id>tag:meteo.gc.ca,2013-04-16:20260904120000</id>
  </entry>
</feed>
"""

FLUX_AVEC_AUTRE_ALERTE = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Alerte de vents violents en vigueur, secteur de Montreal</title>
    <summary type="html">Vents violents attendus.</summary>
    <id>tag:meteo.gc.ca,2013-04-16:20260905080000</id>
  </entry>
</feed>
"""


def _client_factice() -> AlertesMeteoClient:
    """Construit un AlertesMeteoClient sans passer par __init__ (donc sans
    appel réseau de validation au démarrage)."""
    client = AlertesMeteoClient.__new__(AlertesMeteoClient)
    client.feed_url = "https://weather.gc.ca/rss/battleboard/qcrm2_f.xml"
    client._dernier_id_annonce = None
    return client


def _mock_reponse(contenu: bytes) -> MagicMock:
    reponse = MagicMock()
    reponse.content = contenu
    reponse.raise_for_status = MagicMock()
    return reponse


@patch("weather_alerts.requests.get")
def test_obtenir_alerte_sans_alerte_en_vigueur(mock_get):
    mock_get.return_value = _mock_reponse(FLUX_SANS_ALERTE)
    resultat = _client_factice().obtenir_alerte()
    assert resultat == "Aucune alerte météo en vigueur."


@patch("weather_alerts.requests.get")
def test_obtenir_alerte_avec_alerte_active(mock_get):
    mock_get.return_value = _mock_reponse(FLUX_AVEC_ALERTE)
    resultat = _client_factice().obtenir_alerte()
    assert "froid extreme" in resultat.lower()
    # Les balises HTML du résumé ne doivent jamais être dites à voix haute.
    assert "<b>" not in resultat


@patch("weather_alerts._dans_la_periode_silencieuse", return_value=False)
@patch("weather_alerts.requests.get")
def test_sondage_declenche_une_seule_fois_par_alerte(mock_get, _mock_silence):
    """Le sondage périodique ne doit annoncer une alerte qu'une seule fois,
    jamais deux fois pour le même id — même si le flux est revérifié."""
    client = _client_factice()
    annonces = []

    mock_get.return_value = _mock_reponse(FLUX_AVEC_ALERTE)
    client._sonder_une_fois(annonces.append)
    client._sonder_une_fois(annonces.append)  # même alerte, ne redéclenche pas

    assert len(annonces) == 1
    assert "froid extreme" in annonces[0].lower()


@patch("weather_alerts._dans_la_periode_silencieuse", return_value=False)
@patch("weather_alerts.requests.get")
def test_sondage_ignore_l_absence_d_alerte(mock_get, _mock_silence):
    client = _client_factice()
    annonces = []

    mock_get.return_value = _mock_reponse(FLUX_SANS_ALERTE)
    client._sonder_une_fois(annonces.append)

    assert annonces == []


@patch("weather_alerts._dans_la_periode_silencieuse", return_value=True)
@patch("weather_alerts.requests.get")
def test_sondage_ignore_une_alerte_apparue_pendant_la_periode_silencieuse(mock_get, mock_silence):
    """Une alerte détectée pendant la période silencieuse n'est jamais
    annoncée, même une fois la coupure terminée : elle est marquée comme vue
    tout de suite, pas juste retardée."""
    client = _client_factice()
    annonces = []

    mock_get.return_value = _mock_reponse(FLUX_AVEC_ALERTE)
    client._sonder_une_fois(annonces.append)
    assert annonces == []
    assert client._dernier_id_annonce is not None  # vue, pas juste ignorée

    mock_silence.return_value = False  # la coupure se termine
    client._sonder_une_fois(annonces.append)
    assert annonces == []  # toujours la même alerte : jamais annoncée

    # Mais une alerte VRAIMENT nouvelle (id différent), elle, doit être lue.
    mock_get.return_value = _mock_reponse(FLUX_AVEC_AUTRE_ALERTE)
    client._sonder_une_fois(annonces.append)
    assert len(annonces) == 1
    assert "vents violents" in annonces[0].lower()


@patch("weather_alerts.time.sleep")
def test_sondage_periodique_survit_a_une_erreur_inattendue(mock_sleep):
    """Une erreur inattendue pendant un sondage (ex: échec ponctuel de
    synthèse vocale dans on_nouvelle_alerte) ne doit jamais tuer le thread de
    sondage — sinon plus aucune alerte proactive pour le reste de la session,
    sans message d'erreur visible."""
    client = _client_factice()

    class ArretDuTest(Exception):
        pass

    # Premier tour : _sonder_une_fois plante. Deuxième tour : on arrête le
    # test proprement plutôt que de boucler pour de vrai.
    mock_sleep.side_effect = [None, ArretDuTest()]

    with patch.object(client, "_sonder_une_fois", side_effect=RuntimeError("panne ponctuelle")):
        try:
            client._sonder_periodiquement(lambda texte: None, 1)
        except ArretDuTest:
            pass

    # Un deuxième appel à time.sleep prouve que la boucle a continué après
    # l'erreur du premier tour, au lieu de laisser l'exception la tuer.
    assert mock_sleep.call_count == 2


def test_demande_alerte_detecte_les_phrases_declencheuses():
    assert demande_alerte("Y a-t-il une alerte météo ?")
    assert demande_alerte("Est-ce qu'il y a un avertissement météo ?")
    assert not demande_alerte("Quel temps fait-il ?")
    assert not demande_alerte("Quelle heure est-il ?")


@patch("weather_alerts.config.ALERTS_QUIET_HOURS_START", "22:00")
@patch("weather_alerts.config.ALERTS_QUIET_HOURS_END", "08:00")
def test_periode_silencieuse_traverse_minuit():
    assert _dans_la_periode_silencieuse(heure(23, 0))
    assert _dans_la_periode_silencieuse(heure(2, 0))
    assert _dans_la_periode_silencieuse(heure(7, 59))
    assert _dans_la_periode_silencieuse(heure(22, 0))  # borne de début incluse
    assert not _dans_la_periode_silencieuse(heure(8, 0))  # borne de fin exclue
    assert not _dans_la_periode_silencieuse(heure(12, 0))


@patch("weather_alerts.config.ALERTS_QUIET_HOURS_START", "09:00")
@patch("weather_alerts.config.ALERTS_QUIET_HOURS_END", "17:00")
def test_periode_silencieuse_sans_passage_de_minuit():
    assert _dans_la_periode_silencieuse(heure(12, 0))
    assert not _dans_la_periode_silencieuse(heure(8, 0))
    assert not _dans_la_periode_silencieuse(heure(20, 0))


@patch("weather_alerts.config.ALERTS_QUIET_HOURS_START", "22:00")
@patch("weather_alerts.config.ALERTS_QUIET_HOURS_END", "22:00")
def test_periode_silencieuse_desactivee_si_heures_identiques():
    assert not _dans_la_periode_silencieuse(heure(23, 0))
    assert not _dans_la_periode_silencieuse(heure(3, 0))
