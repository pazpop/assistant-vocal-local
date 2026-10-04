"""Donne la date et l'heure actuelles, pour la région configurée (ou une
autre ville explicitement demandée).

Calculé localement (pas d'appel réseau pour la ville par défaut, jamais
indisponible), avec un fuseau horaire EXPLICITE (`config.LOCATION_TIMEZONE`)
plutôt que l'horloge système : ça évite que Jarvis se trompe d'heure si le
fuseau Windows est mal réglé, et ça garantit que l'heure et la météo
(weather.py) parlent toujours de la même région (`config.LOCATION_CITY`),
sans configuration séparée.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

import config
import weather
from trigger import contient_une_phrase

JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
MOIS = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)

# Outil exposé au LLM (même format que WEATHER_TOOLS/TIMER_TOOLS).
DATE_TIME_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "obtenir_date_heure",
            "description": (
                "Donne la date et l'heure actuelles. Omets le paramètre "
                "'ville' si aucune ville n'est explicitement nommée dans la "
                "question : l'outil connaît déjà la ville de l'utilisateur "
                "par défaut, ne demande jamais à l'utilisateur où il se trouve."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ville": {
                        "type": "string",
                        "description": (
                            "Ville pour laquelle donner l'heure, seulement si "
                            "explicitement nommée dans la question (ex: "
                            "\"quelle heure est-il à Tokyo ?\")."
                        ),
                    },
                },
                "required": [],
            },
        },
    },
]


# Phrases qui déclenchent une question de date/heure (comparaison en
# minuscules), utilisées pour router vers llm.ask_tool_direct (voir la
# docstring de cette méthode pour le pourquoi de l'absence d'historique).
DATE_TIME_TRIGGER_PHRASES = (
    "quelle heure",
    "quel jour",
    "quelle date",
    "quel est le jour",
    "quelle est la date",
    "on est quel jour",
)


def demande_date_heure(texte: str) -> bool:
    """Détecte si une phrase transcrite demande la date ou l'heure."""
    return contient_une_phrase(texte, DATE_TIME_TRIGGER_PHRASES)


def obtenir_date_heure(ville: str | None = None) -> str:
    """Renvoie l'heure et la date actuelles, en clair pour le LLM.

    Sans `ville`, utilise le fuseau configuré (`config.LOCATION_TIMEZONE`),
    sans aucun appel réseau. Avec `ville`, géocode cette ville à la volée
    (via weather.geocoder, qui renvoie aussi le fuseau horaire du lieu) pour
    répondre à une question sur l'heure d'un autre endroit."""
    if ville is None:
        fuseau = ZoneInfo(config.LOCATION_TIMEZONE)
        nom = config.LOCATION_CITY
    else:
        try:
            _, _, fuseau_nom = weather.geocoder(ville)
        except RuntimeError:
            return (
                f"Je n'ai pas trouvé la ville « {ville} ». Je ne peux donner "
                f"l'heure que pour {config.LOCATION_CITY} pour l'instant."
            )
        fuseau = ZoneInfo(fuseau_nom)
        nom = ville

    maintenant = datetime.now(fuseau)
    jour = JOURS[maintenant.weekday()]
    mois = MOIS[maintenant.month - 1]
    return (
        f"À {nom}, il est {maintenant.hour} heures "
        f"{maintenant.minute}, nous sommes le {jour} {maintenant.day} {mois} "
        f"{maintenant.year}."
    )


def executer_outil(nom: str, arguments: dict) -> str:
    """Dispatch pour le tool-calling du LLM (même patron que les autres clients)."""
    if nom == "obtenir_date_heure":
        return obtenir_date_heure(ville=arguments.get("ville") or None)
    return f"Outil inconnu : {nom}"
