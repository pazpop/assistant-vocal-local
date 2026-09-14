"""Détection de phrases-déclencheuses (mots-clés) dans une question transcrite.

Utilisé par tous les modules qui décident si une question doit être traitée
par un chemin dédié (météo, alertes, date/heure, minuteur, domotique, reset
de l'historique, fin de conversation) plutôt que par le LLM générique —
évite de répéter la même comparaison partout.
"""


def contient_une_phrase(texte: str, phrases: tuple[str, ...]) -> bool:
    """Vrai si l'une des `phrases` (comparées en minuscules, sans tenir
    compte des espaces en trop) apparaît dans `texte`."""
    texte_normalise = texte.strip().lower()
    return any(phrase in texte_normalise for phrase in phrases)
