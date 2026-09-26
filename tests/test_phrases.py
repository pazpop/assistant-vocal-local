"""Tests pour phrases.py : découpage d'un flux de texte (LLM) en phrases.

Cette logique décide quand une phrase est "assez complète" pour être envoyée
au TTS pendant le streaming du LLM (boucle micro locale et API satellite) —
un bon candidat à tester en isolation, sans micro, LLM ni Piper.
"""
import pytest

from phrases import FIN_DE_PHRASE, decouper_en_phrases, nettoyer_pour_la_voix


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


def test_decouper_produit_chaque_phrase_des_qu_elle_est_complete():
    """Une phrase doit sortir dès que sa ponctuation finale arrive, sans
    attendre la fin du flux — c'est tout l'intérêt du streaming."""
    consomme = []

    def flux():
        for fragment in ["Il fait ", "beau. ", "Et demain", " aussi."]:
            consomme.append(fragment)
            yield fragment

    phrases = decouper_en_phrases(flux())

    assert next(phrases) == "Il fait beau."
    assert consomme == ["Il fait ", "beau. "]  # la suite n'est pas encore lue
    assert next(phrases) == "Et demain aussi."


def test_decouper_garde_le_reste_sans_ponctuation_finale():
    assert list(decouper_en_phrases(["Bonjour. ", "Une suite sans point"])) == [
        "Bonjour.",
        "Une suite sans point",
    ]


def test_decouper_plusieurs_phrases_dans_un_seul_fragment():
    assert list(decouper_en_phrases(["Un. Deux ! Trois ?"])) == ["Un.", "Deux !", "Trois ?"]


def test_decouper_ignore_le_vide():
    assert list(decouper_en_phrases([])) == []
    assert list(decouper_en_phrases(["   ", "\n"])) == []


@pytest.mark.parametrize(
    "brut, attendu",
    [
        ("Voici **le résultat** important.", "Voici le résultat important."),
        ("Un *petit* mot et un _autre_ mot.", "Un petit mot et un autre mot."),
        ("Lance `python main.py` ensuite.", "Lance python main.py ensuite."),
        ("## Titre\nTexte.", "Titre Texte."),
        ("- premier point\n- second point", "premier point second point"),
        ("* puce\n* autre", "puce autre"),
        ("Voir [la doc](https://exemple.org/page) ici.", "Voir la doc ici."),
        ("snake_case_var reste intact.", "snake_case_var reste intact."),
        ("Texte simple, sans rien.", "Texte simple, sans rien."),
        ("**", ""),
    ],
)
def test_nettoyer_pour_la_voix(brut, attendu):
    """Piper lit les symboles Markdown à voix haute (« astérisque »)."""
    assert nettoyer_pour_la_voix(brut) == attendu
