"""Découpage d'un flux de texte (fragments du LLM) en phrases complètes, et
nettoyage d'une phrase avant la synthèse vocale.

Partagé entre la boucle micro locale (main.parler_en_flux) et l'API satellite
(satellite_api) : dans les deux cas, on synthétise et joue phrase par phrase
dès qu'elle est complète, sans attendre la fin de la réponse du LLM.
"""
import re
from typing import Iterable, Iterator

FIN_DE_PHRASE = re.compile(r"([^.!?]*[.!?]+)")

_LIEN = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_TITRE_OU_PUCE = re.compile(r"^[ \t]*(?:#{1,6}|[-*+])[ \t]+", re.MULTILINE)
_SOULIGNE = re.compile(r"(?<!\w)_+([^_\n]+)_+(?!\w)")


def nettoyer_pour_la_voix(texte: str) -> str:
    """Retire la mise en forme Markdown que le LLM ajoute parfois (**gras**,
    *italique*, `code`, titres, puces, liens) : Piper la lirait à voix haute
    (« astérisque astérisque »)."""
    texte = _LIEN.sub(r"\1", texte)
    texte = _TITRE_OU_PUCE.sub("", texte)
    texte = _SOULIGNE.sub(r"\1", texte)
    texte = re.sub(r"(?<=\d)\s*\*\s*(?=\d)", " fois ", texte)  # 2*3, pas du Markdown
    texte = re.sub(r"[*`]+", "", texte)
    return re.sub(r"\s+", " ", texte).strip()


def decouper_en_phrases(fragments: Iterable[str]) -> Iterator[str]:
    """Produit chaque phrase complète dès qu'elle est terminée dans le flux,
    puis le reste éventuel (sans ponctuation finale) une fois le flux fini."""
    tampon = ""
    for fragment in fragments:
        tampon += fragment

        while (trouve := FIN_DE_PHRASE.match(tampon)):
            phrase = trouve.group(1)
            tampon = tampon[len(phrase):]
            phrase = phrase.strip()
            if phrase:
                yield phrase

    reste = tampon.strip()
    if reste:
        yield reste
