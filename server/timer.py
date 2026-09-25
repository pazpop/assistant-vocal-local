"""Minuteurs vocaux ("mets un minuteur de 5 minutes", "liste les minuteurs",
"arrête le minuteur 1").

Chaque minuteur tourne dans un thread à part (threading.Timer) : ça reste
utilisable même si Jarvis est en train d'écouter le mot-clé ou une autre
question au moment où le minuteur sonne. Chacun reçoit un numéro séquentiel
(1, 2, 3...) à sa création, pour pouvoir le désigner ensuite ("annule le
minuteur 2") — ce numéro ne change jamais, même si un minuteur plus ancien
sonne ou est annulé en premier, pour ne jamais désigner accidentellement le
mauvais minuteur.
"""
import itertools
import threading
import time
from typing import Callable

import numpy as np

from trigger import contient_une_phrase

DUREE_MIN_SECONDES = 1
DUREE_MAX_SECONDES = 4 * 60 * 60  # 4h : garde-fou contre une durée délirante


# Outils exposés au LLM (même format que HA_TOOLS/WEATHER_TOOLS).
# lister_minuteurs en premier : si le LLM n'arrive pas à décider quel outil
# appeler, llm.ask_tool_direct se rabat sur le premier de la liste — lister
# (sans argument) est la seule des trois actions qui ne peut jamais échouer
# ni rien changer par erreur.
TIMER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "lister_minuteurs",
            "description": (
                "Donne la liste des minuteurs en cours, ou le temps restant "
                "pour un seul si son numéro est précisé (ex: 'combien de "
                "temps reste-t-il pour le minuteur 1 ?' -> numero=1). "
                "Appelle TOUJOURS cet outil pour toute question sur les "
                "minuteurs en cours ou le temps restant."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "numero": {
                        "type": "integer",
                        "description": (
                            "Numéro du minuteur (1, 2, 3...), donné par cet "
                            "outil. Omets pour lister tous les minuteurs."
                        ),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "demarrer_minuteur",
            "description": (
                "Démarre un minuteur qui sonne après un délai donné. "
                "Convertis toujours la durée demandée par l'utilisateur en "
                "secondes (ex: '5 minutes' -> 300, '2 minutes 30' -> 150)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "secondes": {
                        "type": "integer",
                        "description": "Durée du minuteur en secondes.",
                    },
                    "label": {
                        "type": "string",
                        "description": (
                            "Description courte du minuteur, ex: 'pour les "
                            "pâtes'. Optionnel."
                        ),
                    },
                },
                "required": ["secondes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "annuler_minuteur",
            "description": (
                "Arrête un ou plusieurs minuteurs en cours. Utilise le "
                "numéro donné par l'outil lister_minuteurs (1, 2, 3...), ou "
                "'tous' pour tous les arrêter."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cible": {
                        "type": "string",
                        "description": "Numéro du minuteur à arrêter (ex: '1'), ou 'tous'.",
                    },
                },
                "required": ["cible"],
            },
        },
    },
]


# Phrases qui déclenchent une demande liée aux minuteurs — démarrer, lister
# ou annuler (comparaison en minuscules), utilisées pour router vers
# llm.ask_tool_direct (voir la docstring de cette méthode pour le pourquoi de
# l'absence d'historique). Les trois outils sont fournis ensemble ; le LLM
# choisit celui qui correspond à la question.
TIMER_TRIGGER_PHRASES = (
    "minuteur",
    "chronomètre",
    "compte à rebours",
)


def demande_minuteur(texte: str) -> bool:
    """Détecte si une phrase transcrite concerne les minuteurs (démarrer,
    lister ou annuler)."""
    return contient_une_phrase(texte, TIMER_TRIGGER_PHRASES)


def _formater_duree(secondes: int) -> str:
    """Formate une durée en secondes de façon plus naturelle à l'oral
    ("2 minutes" plutôt que "120 secondes")."""
    if secondes < 60:
        return f"{secondes} seconde{'s' if secondes != 1 else ''}"
    minutes, reste = divmod(secondes, 60)
    duree = f"{minutes} minute{'s' if minutes > 1 else ''}"
    if reste:
        duree += f" {reste} seconde{'s' if reste > 1 else ''}"
    return duree


def generer_sonnerie(
    sample_rate: int, frequence: float = 880.0, duree_bip: float = 0.15, nb_bips: int = 3
) -> np.ndarray:
    """Génère un court carillon (bips sinusoïdaux) pour signaler la fin d'un
    minuteur, sans dépendre d'un fichier audio à fournir avec le projet."""
    t = np.linspace(0, duree_bip, int(sample_rate * duree_bip), endpoint=False)
    bip = 0.3 * np.sin(2 * np.pi * frequence * t).astype(np.float32)
    silence = np.zeros(int(sample_rate * 0.1), dtype=np.float32)

    morceaux = []
    for _ in range(nb_bips):
        morceaux.append(bip)
        morceaux.append(silence)
    return np.concatenate(morceaux)


class TimerManager:
    """Dispatch + exécution des minuteurs demandés par le LLM."""

    def __init__(self, on_expire: Callable[[str, str | None], None]):
        """`on_expire(label, origine)` est appelé (dans un thread à part)
        quand un minuteur sonne — à l'appelant (main.py) de parler et jouer
        un son au bon endroit : `label` = "pour les pâtes" (ou "" si aucun),
        `origine` = zone du satellite qui l'a demandé (None = ce PC)."""
        self._on_expire = on_expire
        # Numéros attribués une seule fois, jamais réutilisés : même si le
        # minuteur 1 sonne avant le minuteur 2, celui-ci reste "minuteur 2"
        # pour toujours — jamais renuméroté en "minuteur 1" à la place.
        self._prochain_numero = itertools.count(1)
        self._minuteries: dict[int, dict] = {}
        self._verrou = threading.Lock()

    def demarrer(self, secondes: int, label: str = "", origine: str | None = None) -> str:
        if not isinstance(secondes, (int, float)) or not (
            DUREE_MIN_SECONDES <= secondes <= DUREE_MAX_SECONDES
        ):
            return (
                f"Durée de minuteur invalide (doit être entre {DUREE_MIN_SECONDES} "
                f"et {DUREE_MAX_SECONDES} secondes)."
            )

        numero = next(self._prochain_numero)

        def _a_expiration() -> None:
            with self._verrou:
                self._minuteries.pop(numero, None)
            self._on_expire(label, origine)

        minuterie = threading.Timer(secondes, _a_expiration)
        minuterie.daemon = True
        with self._verrou:
            self._minuteries[numero] = {
                "timer": minuterie,
                "label": label,
                "heure_fin": time.time() + secondes,
            }
        minuterie.start()

        duree = _formater_duree(int(secondes))
        return f"Minuteur{f' {label}' if label else ''} de {duree} démarré."

    def lister(self, numero: int | None = None) -> str:
        if numero is not None:
            try:
                numero = int(numero)
            except (TypeError, ValueError):
                return f"Je n'ai pas compris de quel minuteur il s'agit ({numero!r})."

        with self._verrou:
            etats = sorted(
                (n, e["label"], max(0, round(e["heure_fin"] - time.time())))
                for n, e in self._minuteries.items()
            )

        if numero is not None:
            trouve = next((e for e in etats if e[0] == numero), None)
            if trouve is None:
                return f"Je n'ai pas trouvé de minuteur numéro {numero}."
            _, label, restant = trouve
            nom = f"minuteur {numero}{f' {label}' if label else ''}"
            return f"Pour le {nom}, il reste {_formater_duree(restant)}."

        if not etats:
            return "Aucun minuteur en cours."

        descriptions = [
            f"minuteur {n}{f' {label}' if label else ''} ({_formater_duree(restant)} restantes)"
            for n, label, restant in etats
        ]
        mot = "minuteur" if len(etats) == 1 else "minuteurs"
        return f"Il y a {len(etats)} {mot} en cours : " + ", ".join(descriptions) + "."

    def annuler(self, cible: str) -> str:
        cible_normalisee = str(cible).strip().lower()

        with self._verrou:
            if cible_normalisee in ("tous", "tout", "toutes"):
                if not self._minuteries:
                    return "Aucun minuteur à arrêter."
                n = len(self._minuteries)
                for etat in self._minuteries.values():
                    etat["timer"].cancel()
                self._minuteries.clear()
                if n == 1:
                    return "J'ai arrêté le minuteur."
                return f"J'ai arrêté les {n} minuteurs."

            try:
                numero = int(cible_normalisee)
            except ValueError:
                return f"Je n'ai pas compris quel minuteur arrêter ({cible!r})."

            etat = self._minuteries.pop(numero, None)

        if etat is None:
            return f"Je n'ai pas trouvé de minuteur numéro {numero}."
        etat["timer"].cancel()
        label = etat["label"]
        nom = f"minuteur {numero}{f' {label}' if label else ''}"
        return f"J'ai arrêté le {nom}."

    def executer_outil(self, nom: str, arguments: dict, origine: str | None = None) -> str:
        """Dispatch pour le tool-calling du LLM (même patron que les autres
        clients). `origine` : voir __init__ (seul démarrer_minuteur s'en sert)."""
        try:
            if nom == "demarrer_minuteur":
                return self.demarrer(arguments["secondes"], arguments.get("label", ""), origine)
            if nom == "lister_minuteurs":
                return self.lister(arguments.get("numero"))
            if nom == "annuler_minuteur":
                return self.annuler(arguments["cible"])
            return f"Outil minuteur inconnu : {nom}"
        except KeyError as exc:
            return f"Argument manquant pour l'outil '{nom}' : {exc}"
