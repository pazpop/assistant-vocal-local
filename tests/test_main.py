"""Tests pour la logique de routage et d'outils de main.py (routes directes,
outils disponibles) — le découpage en phrases, lui, est dans test_phrases.py.
"""
from unittest.mock import Mock, patch

from main import construire_outils, construire_routes_directes
from timer import TimerManager
from weather_alerts import ALERT_TOOLS
from weather import WEATHER_TOOLS


def test_construire_routes_directes_priorise_alerte_avant_meteo():
    """"alerte météo" contient le mot "météo" : si la route météo était
    vérifiée en premier, une question d'alerte serait mal aiguillée vers
    l'outil météo (mauvaise réponse, jamais celle demandée)."""
    with patch("timer.threading.Timer"):
        gestionnaire = TimerManager(on_expire=lambda label, origine: None)
        routes = construire_routes_directes(
            ha_client=None,
            weather_client=Mock(),
            timer_manager=gestionnaire,
            alertes_client=Mock(),
        )

    matcher, _executeur = routes[0]
    assert matcher("Y a-t-il une alerte météo ?") == ALERT_TOOLS


def test_construire_routes_directes_ignore_les_clients_absents():
    with patch("timer.threading.Timer"):
        gestionnaire = TimerManager(on_expire=lambda label, origine: None)
        routes = construire_routes_directes(
            ha_client=None, weather_client=None, timer_manager=gestionnaire, alertes_client=None
        )

    assert not any(matcher("météo") == WEATHER_TOOLS for matcher, _ in routes)


def test_construire_outils_noms_uniques_avec_tous_les_clients():
    """Garde-fou : si deux modules déclarent un outil de même nom, le
    dispatch de l'un écraserait silencieusement celui de l'autre. L'assert
    dans construire_outils() doit lever avant d'en arriver là — ce test
    couvre le cas le plus chargé (tous les clients présents à la fois)."""
    with patch("timer.threading.Timer"):
        gestionnaire = TimerManager(on_expire=lambda label, origine: None)
        construire_outils(
            ha_client=Mock(),
            weather_client=Mock(),
            timer_manager=gestionnaire,
            alertes_client=Mock(),
        )  # ne doit pas lever


def test_construire_outils_dispatche_les_trois_outils_minuteur():
    """construire_outils() n'est utilisé que par le chemin de repli générique
    (ask_with_tools, sans trigger dédié) : si son dispatch ne connaît pas un
    nom d'outil que TIMER_TOOLS expose bien (lister_minuteurs, annuler_minuteur),
    le LLM reçoit "Outil indisponible" au lieu d'une vraie réponse."""
    with patch("timer.threading.Timer"):
        gestionnaire = TimerManager(on_expire=lambda label, origine: None)
        gestionnaire.demarrer(60, "")

        _tools, executer_outil = construire_outils(
            ha_client=None, weather_client=None, timer_manager=gestionnaire, alertes_client=None
        )

        assert "minuteur 1" in executer_outil("lister_minuteurs", {})
        assert "arrêté" in executer_outil("annuler_minuteur", {"cible": "1"})


def test_parler_en_flux_pose_la_sentinelle_meme_si_le_llm_plante():
    """Sans sentinelle, le thread lecteur attend à vie et l'utilisateur
    n'entend rien après une erreur (Ollama arrêté...)."""
    import queue

    import pytest

    from main import parler_en_flux

    def flux_qui_plante():
        yield "Bonjour. "
        raise ConnectionError("Ollama arrêté")

    tts = Mock()
    tts.synthesize.return_value = "audio"
    file_audio = queue.Queue()

    with pytest.raises(ConnectionError):
        parler_en_flux(flux_qui_plante(), tts, file_audio)

    assert [file_audio.get_nowait(), file_audio.get_nowait()] == ["audio", None]


def test_sous_verrou_libere_le_verrou_si_le_flux_est_abandonne():
    import threading

    from main import sous_verrou

    verrou = threading.Lock()
    flux = sous_verrou(verrou, iter(["a", "b"]))
    assert next(flux) == "a"
    assert verrou.locked()

    flux.close()  # le client s'est déconnecté en cours de route
    assert not verrou.locked()


def test_les_minuteurs_d_un_satellite_gardent_son_origine():
    with patch("timer.threading.Timer") as mock_timer:
        appels = []
        gestionnaire = TimerManager(on_expire=lambda label, origine: appels.append(origine))
        _, executer_outil = construire_outils(
            ha_client=None, weather_client=None, timer_manager=gestionnaire,
            alertes_client=None, origine="cuisine",
        )
        executer_outil("demarrer_minuteur", {"secondes": 5})
        _, callback_expiration = mock_timer.call_args[0]

    callback_expiration()
    assert appels == ["cuisine"]
