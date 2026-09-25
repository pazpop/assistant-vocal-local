"""Tests pour weather.py : formatage de la météo, sans appel réseau réel
(requests.get est mocké)."""
from unittest.mock import MagicMock, patch

import pytest
import requests

from weather import (
    DESCRIPTIONS_METEO,
    METEO_ACTUELLE_TOOLS,
    PREVISION_TOOLS,
    WeatherClient,
    demande_meteo,
    geocoder,
    outils_meteo,
)


def _client_factice() -> WeatherClient:
    """Construit un WeatherClient sans passer par __init__ (donc sans
    appeler l'API de géocodage réelle)."""
    client = WeatherClient.__new__(WeatherClient)
    client.ville = "Montréal"
    client.latitude = 45.78
    client.longitude = -74.01
    client._cache = {}
    return client


def test_descriptions_meteo_couvre_les_codes_courants():
    assert DESCRIPTIONS_METEO[0] == "un ciel dégagé"
    assert DESCRIPTIONS_METEO[61] == "de la pluie légère"
    assert DESCRIPTIONS_METEO[95] == "un orage"


@patch("weather.requests.get")
def test_obtenir_meteo_formate_correctement(mock_get):
    mock_reponse = MagicMock()
    mock_reponse.json.return_value = {
        "current": {
            "temperature_2m": 20.4,
            "apparent_temperature": 24.6,
            "weather_code": 0,
            "wind_speed_10m": 14.7,
        }
    }
    mock_get.return_value = mock_reponse

    resultat = _client_factice().obtenir_meteo()

    assert "Montréal" in resultat
    assert "20 degrés" in resultat
    assert "ressenti 25 degrés" in resultat  # arrondi de 24.6
    assert "ciel dégagé" in resultat
    assert "vent de 15 km/h" in resultat  # arrondi de 14.7


@patch("weather.requests.get", side_effect=requests.exceptions.ConnectionError("boom"))
def test_obtenir_meteo_gere_les_erreurs_reseau(mock_get):
    resultat = _client_factice().obtenir_meteo()
    assert "erreur" in resultat.lower()


@patch("weather.requests.get")
def test_obtenir_meteo_n_annonce_jamais_zero_degre_si_un_champ_manque(mock_get):
    """Open-Meteo qui omet un champ ne doit pas devenir « 0 degrés »."""
    mock_reponse = MagicMock()
    mock_reponse.json.return_value = {"current": {"weather_code": 0}}
    mock_get.return_value = mock_reponse

    resultat = _client_factice().obtenir_meteo()

    assert "erreur" in resultat.lower()
    assert "degrés" not in resultat


@patch("weather.requests.get")
def test_obtenir_meteo_gere_un_json_invalide(mock_get):
    mock_reponse = MagicMock()
    mock_reponse.json.side_effect = ValueError("pas du JSON")
    mock_get.return_value = mock_reponse

    assert "erreur" in _client_factice().obtenir_meteo().lower()


def test_executer_outil_dispatch():
    client = _client_factice()
    with patch.object(client, "obtenir_meteo", return_value="ok"):
        assert client.executer_outil("obtenir_meteo", {}) == "ok"
    assert "inconnu" in client.executer_outil("autre_chose", {}).lower()


def test_demande_meteo_detecte_les_formulations_courantes():
    for question in (
        "Quel temps fait-il dehors ?",
        "Quelle est la météo aujourd'hui ?",
        "Il pleut ?",
        "Est-ce qu'il fait beau ?",
        "Et sinon quel temps qu'il fait ?",
    ):
        assert demande_meteo(question), question


def test_demande_meteo_ignore_les_questions_sans_rapport():
    for question in (
        "Quelle heure est-il ?",
        "Allume la lumière du salon",
        "Raconte-moi une blague",
    ):
        assert not demande_meteo(question), question


@patch("weather.requests.get")
def test_geocoder_renvoie_lat_lon_fuseau(mock_get):
    mock_reponse = MagicMock()
    mock_reponse.json.return_value = {
        "results": [{"latitude": 48.85, "longitude": 2.35, "timezone": "Europe/Paris"}]
    }
    mock_get.return_value = mock_reponse

    assert geocoder("Paris") == (48.85, 2.35, "Europe/Paris")


@patch("weather.requests.get")
def test_geocoder_leve_si_aucun_resultat(mock_get):
    mock_reponse = MagicMock()
    mock_reponse.json.return_value = {"results": []}
    mock_get.return_value = mock_reponse

    with pytest.raises(RuntimeError):
        geocoder("Ville Imaginaire")


@patch("weather.requests.get", side_effect=requests.exceptions.ConnectionError("boom"))
def test_geocoder_leve_en_cas_d_erreur_reseau(mock_get):
    with pytest.raises(RuntimeError):
        geocoder("Paris")


def test_init_leve_une_erreur_si_le_geocodage_echoue():
    """Pas de repli (ex: géolocalisation IP) : uniquement config.yml. Si ça
    échoue, la météo doit rester désactivée plutôt que de deviner."""
    with patch("weather.geocoder", side_effect=RuntimeError("ville introuvable")):
        with pytest.raises(RuntimeError):
            WeatherClient()


@patch("weather.geocoder")
@patch("weather.requests.get")
def test_obtenir_meteo_avec_ville_differente_geocode_a_la_volee(mock_get, mock_geocoder):
    mock_geocoder.return_value = (48.85, 2.35, "Europe/Paris")
    mock_reponse = MagicMock()
    mock_reponse.json.return_value = {
        "current": {
            "temperature_2m": 15.0,
            "apparent_temperature": 14.0,
            "weather_code": 61,
            "wind_speed_10m": 10.0,
        }
    }
    mock_get.return_value = mock_reponse

    client = _client_factice()
    resultat = client.obtenir_meteo(ville="Paris")

    mock_geocoder.assert_called_once_with("Paris")
    assert "Paris" in resultat
    assert "Montréal" not in resultat
    # Utilise bien les coordonnées de Paris, pas celles mises en cache
    _, kwargs = mock_get.call_args
    assert kwargs["params"]["latitude"] == 48.85


@patch("weather.geocoder")
@patch("weather.requests.get")
def test_obtenir_meteo_sans_ville_utilise_la_position_en_cache(mock_get, mock_geocoder):
    mock_reponse = MagicMock()
    mock_reponse.json.return_value = {
        "current": {"temperature_2m": 20.0, "apparent_temperature": 20.0, "weather_code": 0, "wind_speed_10m": 10.0}
    }
    mock_get.return_value = mock_reponse

    client = _client_factice()
    resultat = client.obtenir_meteo()

    mock_geocoder.assert_not_called()
    assert "Montréal" in resultat


@patch("weather.geocoder", side_effect=RuntimeError("ville introuvable"))
def test_obtenir_meteo_ville_introuvable_ne_plante_pas(mock_geocoder):
    client = _client_factice()
    resultat = client.obtenir_meteo(ville="Ville Imaginaire")

    assert "Ville Imaginaire" in resultat
    assert "Montréal" in resultat  # rappelle la ville qu'il connaît


@patch("weather.requests.get")
def test_obtenir_meteo_reutilise_le_cache_sans_nouvel_appel_reseau(mock_get):
    mock_reponse = MagicMock()
    mock_reponse.json.return_value = {
        "current": {"temperature_2m": 20.0, "apparent_temperature": 20.0, "weather_code": 0, "wind_speed_10m": 10.0}
    }
    mock_get.return_value = mock_reponse

    client = _client_factice()
    premier = client.obtenir_meteo()
    deuxieme = client.obtenir_meteo()

    assert premier == deuxieme
    mock_get.assert_called_once()  # le deuxième appel n'a pas retouché le réseau


@patch("weather.requests.get")
def test_obtenir_meteo_cache_separe_par_ville(mock_get):
    mock_reponse = MagicMock()
    mock_reponse.json.return_value = {
        "current": {"temperature_2m": 20.0, "apparent_temperature": 20.0, "weather_code": 0, "wind_speed_10m": 10.0}
    }
    mock_get.return_value = mock_reponse

    client = _client_factice()
    with patch("weather.geocoder", return_value=(48.85, 2.35, "Europe/Paris")):
        client.obtenir_meteo(ville="Paris")
    client.obtenir_meteo()  # ville par défaut : ne doit pas réutiliser le cache de Paris

    assert mock_get.call_count == 2


@patch("weather.requests.get")
def test_obtenir_meteo_recontacte_apres_expiration_du_cache(mock_get):
    mock_reponse = MagicMock()
    mock_reponse.json.return_value = {
        "current": {"temperature_2m": 20.0, "apparent_temperature": 20.0, "weather_code": 0, "wind_speed_10m": 10.0}
    }
    mock_get.return_value = mock_reponse

    client = _client_factice()
    with patch("weather.time.time", return_value=1000.0):
        client.obtenir_meteo()
    with patch("weather.time.time", return_value=1000.0 + 601):  # après le TTL de 600s
        client.obtenir_meteo()

    assert mock_get.call_count == 2


def test_obtenir_meteo_ne_met_jamais_une_erreur_en_cache():
    client = _client_factice()
    with patch("weather.geocoder", side_effect=RuntimeError("ville introuvable")):
        client.obtenir_meteo(ville="Ville Imaginaire")

    assert "Ville Imaginaire" not in client._cache


def _reponse_prevision(pluie=(0, 10, 60)):
    reponse = MagicMock()
    reponse.json.return_value = {
        "daily": {
            "weather_code": [0, 3, 61],
            "temperature_2m_max": [22.4, 20.6, 15.0],
            "temperature_2m_min": [10.0, 11.5, 9.2],
            "precipitation_probability_max": list(pluie),
        }
    }
    return reponse


@patch("weather.requests.get")
def test_obtenir_prevision_demain(mock_get):
    mock_get.return_value = _reponse_prevision()

    resultat = _client_factice().obtenir_prevision("demain")

    assert resultat == "Demain à Montréal, on prévoit un ciel couvert, entre 12 et 21 degrés."
    _, kwargs = mock_get.call_args
    assert kwargs["params"]["forecast_days"] == 3


@patch("weather.requests.get")
def test_obtenir_prevision_apres_demain_avec_risque_de_pluie(mock_get):
    mock_get.return_value = _reponse_prevision()

    resultat = _client_factice().obtenir_prevision("apres-demain")  # sans accent, comme le STT peut l'écrire

    assert resultat.startswith("Après-demain à Montréal, on prévoit de la pluie légère")
    assert "60 pour cent de probabilité de précipitations" in resultat


@patch("weather.requests.get")
def test_obtenir_prevision_jour_inconnu_donne_demain(mock_get):
    mock_get.return_value = _reponse_prevision()
    assert _client_factice().obtenir_prevision("dans trois mois").startswith("Demain")


@patch("weather.requests.get")
def test_obtenir_prevision_donnees_incompletes_ne_plante_pas(mock_get):
    reponse = MagicMock()
    reponse.json.return_value = {"daily": {"weather_code": [0]}}
    mock_get.return_value = reponse

    assert "erreur" in _client_factice().obtenir_prevision("demain").lower()


@patch("weather.requests.get")
def test_previsions_de_jours_differents_ne_partagent_pas_le_cache(mock_get):
    mock_get.return_value = _reponse_prevision()
    client = _client_factice()

    demain = client.obtenir_prevision("demain")
    apres = client.obtenir_prevision("après-demain")
    client.obtenir_prevision("demain")

    assert demain != apres
    assert mock_get.call_count == 2  # le 2e « demain » vient du cache


def test_executer_outil_prevision():
    client = _client_factice()
    with patch.object(client, "obtenir_prevision", return_value="ok") as prevision:
        assert client.executer_outil("obtenir_prevision_meteo", {"jour": "après-demain", "ville": "Paris"}) == "ok"
        prevision.assert_called_once_with(jour="après-demain", ville="Paris")
        client.executer_outil("obtenir_prevision_meteo", {})
        prevision.assert_called_with(jour="demain", ville=None)


def test_outils_meteo_choisit_la_prevision_pour_demain():
    """Choix déterministe (pas laissé au LLM) : « demain » ne doit jamais
    donner la météo actuelle."""
    assert outils_meteo("Quelle est la météo pour demain ?") == PREVISION_TOOLS
    assert outils_meteo("Il va pleuvoir demain ?") == PREVISION_TOOLS
    assert outils_meteo("Quel temps fera-t-il après-demain ?") == PREVISION_TOOLS
    assert outils_meteo("Quelle est la météo ?") == METEO_ACTUELLE_TOOLS
    assert outils_meteo("Quelle heure est-il demain ?") is None
