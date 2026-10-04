"""Tests pour trigger.py : détection de phrase-déclencheuse partagée par
tous les modules qui en ont besoin (météo, alertes, date/heure, minuteur,
domotique, reset de l'historique, fin de conversation)."""
from trigger import contient_une_phrase


def test_contient_une_phrase_detecte_une_correspondance():
    assert contient_une_phrase("Quel temps fait-il ?", ("météo", "quel temps fait"))


def test_contient_une_phrase_insensible_a_la_casse():
    assert contient_une_phrase("QUELLE HEURE EST-IL ?", ("quelle heure",))


def test_contient_une_phrase_ignore_les_espaces_en_trop():
    assert contient_une_phrase("   oublie tout   ", ("oublie tout",))


def test_contient_une_phrase_sans_correspondance():
    assert not contient_une_phrase("Raconte-moi une blague", ("météo", "minuteur"))
