"""Tests pour la logique de découpage de phrases dans main.py.

Cette regex décide quand une phrase est "assez complète" pour être envoyée
au TTS pendant le streaming du LLM — un bon candidat à tester en isolation,
sans dépendre du micro, du LLM ou de Piper.
"""
from unittest.mock import patch

from main import FIN_DE_PHRASE, construire_outils
from timer import TimerManager


def test_construire_outils_dispatche_les_trois_outils_minuteur():
    """construire_outils() n'est utilisé que par le chemin de repli générique
    (ask_with_tools, sans trigger dédié) : si son dispatch ne connaît pas un
    nom d'outil que TIMER_TOOLS expose bien (lister_minuteurs, annuler_minuteur),
    le LLM reçoit "Outil indisponible" au lieu d'une vraie réponse."""
    with patch("timer.threading.Timer"):
        gestionnaire = TimerManager(on_expire=lambda label: None)
        gestionnaire.demarrer(60, "")

        _tools, executer_outil = construire_outils(
            ha_client=None, weather_client=None, timer_manager=gestionnaire, alertes_client=None
        )

        assert "minuteur 1" in executer_outil("lister_minuteurs", {})
        assert "arrêté" in executer_outil("annuler_minuteur", {"cible": "1"})


def test_phrase_simple():
    assert FIN_DE_PHRASE.match("Bonjour.").group(1) == "Bonjour."


def test_phrase_avec_virgule_pas_encore_complete():
    tampon = "Il fait beau, "
    assert FIN_DE_PHRASE.match(tampon) is None


def test_extrait_seulement_la_premiere_phrase():
    tampon = "Première phrase. Deuxième phrase en cours"
    trouve = FIN_DE_PHRASE.match(tampon)
    assert trouve.group(1) == "Première phrase."
    reste = tampon[trouve.end():]
    assert reste == " Deuxième phrase en cours"


def test_point_d_interrogation_et_exclamation():
    assert FIN_DE_PHRASE.match("Vraiment ?!").group(1) == "Vraiment ?!"
