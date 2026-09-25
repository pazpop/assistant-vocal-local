"""Découpage d'un flux de texte (fragments du LLM) en phrases complètes.

Partagé entre la boucle micro locale (main.parler_en_flux) et l'API satellite
(satellite_api) : dans les deux cas, on synthétise et joue phrase par phrase
dès qu'elle est complète, sans attendre la fin de la réponse du LLM.
"""
import re
from typing import Iterable, Iterator

FIN_DE_PHRASE = re.compile(r"([^.!?]*[.!?]+)")


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
