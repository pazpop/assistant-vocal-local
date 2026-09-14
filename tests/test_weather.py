"""Tests pour weather.py : formatage de la météo, sans appel réseau réel
(requests.get est mocké)."""
from unittest.mock import MagicMock, patch

import pytest
import requests

from weather import DESCRIPTIONS_METEO, WeatherClient, demande_meteo, geocoder


def _client_factice() -> WeatherClient:
    """Construit un WeatherClient sans passer par __init__ (donc sans
    appeler l'API de géocodage réelle)."""
    client = WeatherClient.__new__(WeatherClient)
    client.ville = "Montréal"
    client.latitude = 45.78
    client.longitude = -74.01
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
        "current": {"temperature_2m": 20.0, "apparent_temperature": 20.0, "weather_code": 0}
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
