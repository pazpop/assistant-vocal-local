"""Tests pour date_time.py : formatage, avec une horloge figée (pas de
dépendance à l'heure réelle d'exécution du test)."""
from datetime import datetime
from unittest.mock import patch

import date_time


@patch("date_time.datetime")
def test_obtenir_date_heure_formate_correctement(mock_datetime):
    # Mercredi 15 avril 2026, 9h05.
    mock_datetime.now.return_value = datetime(2026, 4, 15, 9, 5)

    resultat = date_time.obtenir_date_heure()

    assert "9 heures 5" in resultat
    assert "mercredi" in resultat
    assert "15 avril 2026" in resultat
    assert date_time.config.LOCATION_CITY in resultat


def test_utilise_le_fuseau_horaire_configure():
    """Vérifie que le fuseau LOCATION_TIMEZONE se résout bien (tzdata
    installé) et que l'heure renvoyée correspond à ce fuseau, pas à un
    éventuel fuseau système mal réglé."""
    from zoneinfo import ZoneInfo

    heure_attendue = datetime.now(ZoneInfo(date_time.config.LOCATION_TIMEZONE)).hour
    resultat = date_time.obtenir_date_heure()
    assert f"{heure_attendue} heures" in resultat


def test_executer_outil_dispatch():
    with patch("date_time.obtenir_date_heure", return_value="ok"):
        assert date_time.executer_outil("obtenir_date_heure", {}) == "ok"
    assert "inconnu" in date_time.executer_outil("autre_chose", {}).lower()


def test_executer_outil_transmet_la_ville():
    with patch("date_time.obtenir_date_heure", return_value="ok") as mock_obtenir:
        date_time.executer_outil("obtenir_date_heure", {"ville": "Tokyo"})
    mock_obtenir.assert_called_once_with(ville="Tokyo")


@patch("date_time.datetime")
def test_obtenir_date_heure_avec_ville_geocode_le_fuseau(mock_datetime):
    from zoneinfo import ZoneInfo

    mock_datetime.now.return_value = datetime(2026, 4, 15, 9, 5, tzinfo=ZoneInfo("Asia/Tokyo"))

    with patch("date_time.weather.geocoder", return_value=(35.68, 139.69, "Asia/Tokyo")) as mock_geocoder:
        resultat = date_time.obtenir_date_heure(ville="Tokyo")

    mock_geocoder.assert_called_once_with("Tokyo")
    assert "Tokyo" in resultat
    assert date_time.config.LOCATION_CITY not in resultat


def test_obtenir_date_heure_ville_introuvable_ne_plante_pas():
    with patch("date_time.weather.geocoder", side_effect=RuntimeError("ville introuvable")):
        resultat = date_time.obtenir_date_heure(ville="Ville Imaginaire")

    assert "Ville Imaginaire" in resultat
    assert date_time.config.LOCATION_CITY in resultat


def test_demande_date_heure_detecte_les_formulations_courantes():
    for question in (
        "Quelle heure est-il ?",
        "Quelle heure est-il à Paris ?",
        "On est quel jour ?",
        "Quelle est la date aujourd'hui ?",
    ):
        assert date_time.demande_date_heure(question), question


def test_demande_date_heure_ignore_les_questions_sans_rapport():
    for question in (
        "Quel temps fait-il dehors ?",
        "Allume la lumière du salon",
        "Raconte-moi une blague",
    ):
        assert not date_time.demande_date_heure(question), question
