"""Tests pour le dispatch d'outils domotique (sans appeler un vrai serveur HA)."""
from unittest.mock import MagicMock, patch

import config
from home_assistant import HomeAssistantClient, demande_domotique


def _client_factice() -> HomeAssistantClient:
    """Construit un HomeAssistantClient sans passer par __init__ (pas de
    jeton ni de vérification réseau nécessaires pour ce test unitaire)."""
    client = HomeAssistantClient.__new__(HomeAssistantClient)
    client._appeler_service = MagicMock(return_value="ok")
    return client


def test_executer_outil_allumer():
    client = _client_factice()
    resultat = client.executer_outil("allumer", {"entity_id": "light.salon"})
    client._appeler_service.assert_called_once_with("light", "turn_on", "light.salon")
    assert resultat == "ok"


def test_executer_outil_inconnu():
    client = _client_factice()
    resultat = client.executer_outil("faire_le_cafe", {})
    assert "inconnu" in resultat.lower()


def test_executer_outil_domaine_non_autorise():
    """Le LLM ne doit pas pouvoir piloter un domaine hors light/switch
    (ex: un verrou) même s'il fournit un entity_id de ce domaine."""
    client = _client_factice()
    resultat = client.executer_outil("allumer", {"entity_id": "lock.porte_entree"})
    client._appeler_service.assert_not_called()
    assert "non autorisé" in resultat.lower()


def test_executer_outil_argument_manquant():
    client = _client_factice()
    resultat = client.executer_outil("allumer", {})
    client._appeler_service.assert_not_called()
    assert "argument manquant" in resultat.lower()


def test_appeler_service_confirmation_parlable_avec_alias():
    """La confirmation doit être directement utilisable telle quelle par
    llm.ask_tool_direct (sans reformulation LLM) : nom court si un alias est
    configuré, sinon l'entity_id brut."""
    client = HomeAssistantClient.__new__(HomeAssistantClient)
    client.base_url = "http://ha.local"
    client.verify_ssl = True
    client.headers = {}

    reponse_factice = MagicMock()
    reponse_factice.raise_for_status = MagicMock()

    with patch("home_assistant.requests.post", return_value=reponse_factice):
        with patch.object(
            config, "HA_DEVICE_ALIASES", {"light.salon_gauche": "lumière salon gauche"}
        ):
            resultat = client._appeler_service("light", "turn_on", "light.salon_gauche")
            assert resultat == "lumière salon gauche : allumé."

            resultat = client._appeler_service("light", "turn_off", "light.salon")
            assert resultat == "light.salon : éteint."


def test_demande_domotique_detecte_allumer_et_eteindre():
    assert demande_domotique("Allume la lumière de la cuisine") == "allumer"
    assert demande_domotique("Peux-tu allumer le salon ?") == "allumer"
    assert demande_domotique("Éteins la lumière de la cuisine") == "eteindre"
    assert demande_domotique("Peux-tu éteindre le salon ?") == "eteindre"
    assert demande_domotique("Quel temps fait-il ?") is None
