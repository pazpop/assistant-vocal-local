"""Client météo pour Jarvis, via Open-Meteo.

Open-Meteo est gratuit et ne demande ni clé API ni compte — cohérent avec la
philosophie du projet (minimiser les dépendances tierces qui imposent une
inscription). Attention : réservé à un usage NON commercial (licence des
données CC BY 4.0). Attribution recommandée par Open-Meteo dans toute
réutilisation publique : "Weather data by Open-Meteo.com".

La localisation vient uniquement de config.yml (LOCATION_GEOCODE_QUERY) —
pas de géolocalisation IP ni d'autre repli : si elle ne peut pas être
géocodée, la météo démarre désactivée avec une erreur claire.
"""
import time

import requests

import config
from trigger import contient_une_phrase

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Durée de mise en cache d'une réponse météo (secondes) : évite de
# resolliciter Open-Meteo à chaque question répétée sur la même ville dans
# ce laps de temps (la météo ne change pas assez vite pour que ce soit
# nécessaire) — bon citoyen vis-à-vis d'une API gratuite, et réponse
# immédiate en cas de répétition.
CACHE_TTL_SECONDES = 600

# Jours de prévision acceptés -> décalage en jours (l'API en donne 3 : aujourd'hui + 2).
JOURS_PREVISION = {"demain": 1, "après-demain": 2}

# Table de correspondance des codes météo WMO (documentés par Open-Meteo :
# https://open-meteo.com/en/docs) vers une description parlée en français.
DESCRIPTIONS_METEO = {
    0: "un ciel dégagé",
    1: "un ciel plutôt dégagé",
    2: "un ciel partiellement nuageux",
    3: "un ciel couvert",
    45: "du brouillard",
    48: "du brouillard givrant",
    51: "une bruine légère",
    53: "une bruine modérée",
    55: "une bruine dense",
    56: "une bruine verglaçante légère",
    57: "une bruine verglaçante dense",
    61: "de la pluie légère",
    63: "de la pluie modérée",
    65: "de la forte pluie",
    66: "de la pluie verglaçante légère",
    67: "de la pluie verglaçante forte",
    71: "de légères chutes de neige",
    73: "des chutes de neige modérées",
    75: "de fortes chutes de neige",
    77: "des grains de neige",
    80: "des averses de pluie légères",
    81: "des averses de pluie modérées",
    82: "des averses de pluie violentes",
    85: "de légères averses de neige",
    86: "de fortes averses de neige",
    95: "un orage",
    96: "un orage avec un peu de grêle",
    99: "un orage avec de la grêle",
}

_PARAM_VILLE = {
    "type": "string",
    "description": (
        "Ville pour laquelle donner la météo, seulement si explicitement "
        "nommée dans la question (ex: \"quel temps fait-il à Paris ?\")."
    ),
}
_AIDE_VILLE = (
    "Omets le paramètre 'ville' si aucune ville n'est explicitement nommée "
    "dans la question : l'outil connaît déjà la ville de l'utilisateur, ne "
    "demande jamais à l'utilisateur où il se trouve."
)

# Outils exposés au LLM (même format que HA_TOOLS dans home_assistant.py) :
# un seul outil à la fois pour ask_tool_direct, voir outils_meteo().
METEO_ACTUELLE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "obtenir_meteo",
            "description": (
                "Donne la météo actuelle (conditions, température, ressenti, "
                "vent). Appelle TOUJOURS cet outil pour toute question sur le "
                f"temps qu'il fait maintenant. {_AIDE_VILLE}"
            ),
            "parameters": {
                "type": "object",
                "properties": {"ville": _PARAM_VILLE},
                "required": [],
            },
        },
    },
]

PREVISION_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "obtenir_prevision_meteo",
            "description": (
                "Donne la prévision météo de demain ou d'après-demain "
                "(conditions, températures min/max, risque de précipitations). "
                "Appelle TOUJOURS cet outil pour toute question sur le temps "
                f"qu'il fera. {_AIDE_VILLE}"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "jour": {
                        "type": "string",
                        "enum": list(JOURS_PREVISION),
                        "description": "Jour de la prévision (demain par défaut).",
                    },
                    "ville": _PARAM_VILLE,
                },
                "required": [],
            },
        },
    },
]

WEATHER_TOOLS = METEO_ACTUELLE_TOOLS + PREVISION_TOOLS

# Phrases qui déclenchent une question météo (comparaison en minuscules),
# utilisées pour router vers llm.ask_tool_direct plutôt que le LLM générique
# (voir la docstring de cette méthode pour le pourquoi de l'absence
# d'historique).
WEATHER_TRIGGER_PHRASES = (
    "météo",
    "il pleut",
    "il neige",
    "il vente",
    "il fait beau",
    "il fait froid",
    "il fait chaud",
    "prévision",
    "va pleuvoir",
    "va neiger",
    "quel temps fera",
    "quel temps va-t-il faire",
    "fera beau",
    "fera froid",
    "fera chaud",
    "quel temps fait",
    "quel temps qu'il fait",
    "quel temps il fait",
    "temps qu'il fait dehors",
    "fait-il dehors",
)


def demande_meteo(texte: str) -> bool:
    """Détecte si une phrase transcrite demande la météo."""
    return contient_une_phrase(texte, WEATHER_TRIGGER_PHRASES)


def demande_prevision(texte: str) -> bool:
    """Vrai si la question porte sur demain ou après-demain (« après-demain »
    contient « demain »)."""
    return contient_une_phrase(texte, ("demain",))


def outils_meteo(question: str) -> list[dict] | None:
    """L'unique outil météo qui correspond à la question (prévision si elle
    parle de demain, sinon météo actuelle), ou None si ce n'est pas une
    question météo. Choisi ici, pas par le LLM : plus fiable."""
    if not demande_meteo(question):
        return None
    return PREVISION_TOOLS if demande_prevision(question) else METEO_ACTUELLE_TOOLS


def geocoder(requete: str) -> tuple[float, float, str]:
    """Convertit un nom de lieu en (latitude, longitude, fuseau horaire IANA).

    Fonction de module (pas seulement une méthode de WeatherClient) : aussi
    réutilisée par date_time.py pour donner l'heure d'une ville explicitement
    nommée dans la question, sans dupliquer l'appel de géocodage."""
    try:
        reponse = requests.get(
            GEOCODING_URL,
            params={"name": requete, "count": 1, "language": "fr", "format": "json"},
            timeout=5,
        )
        reponse.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Impossible de contacter le service de géocodage Open-Meteo "
            f"pour localiser '{requete}'. Détail : {exc}"
        ) from exc

    resultats = reponse.json().get("results")
    if not resultats:
        raise RuntimeError(f"Aucune ville trouvée pour '{requete}'.")
    premier = resultats[0]
    return premier["latitude"], premier["longitude"], premier.get("timezone", "UTC")


class WeatherClient:
    def __init__(
        self,
        ville: str = config.LOCATION_CITY,
        requete_geocodage: str = config.LOCATION_GEOCODE_QUERY,
    ):
        self.ville = ville
        self.latitude, self.longitude, _ = geocoder(requete_geocodage)
        # {(ville, jour): (timestamp, réponse formatée)} ; ville None = ville
        # par défaut, jour None = météo actuelle.
        self._cache: dict[tuple[str | None, str | None], tuple[float, str]] = {}

    def _lieu(self, ville: str | None) -> tuple[float, float, str] | str:
        """(latitude, longitude, nom) du lieu demandé, ou un message d'erreur
        parlé si la ville est introuvable. Sans `ville`, la position de
        l'utilisateur (déjà géocodée au démarrage) ; avec `ville`, géocodage à
        la volée — un échec ici ne désactive pas la météo, contrairement à un
        échec au démarrage."""
        if ville is None:
            return self.latitude, self.longitude, self.ville
        try:
            latitude, longitude, _ = geocoder(ville)
        except RuntimeError:
            return (
                f"Je n'ai pas trouvé la ville « {ville} ». Je ne peux "
                f"donner la météo que pour {self.ville} pour l'instant."
            )
        return latitude, longitude, ville

    def _repondre(self, cle: tuple[str | None, str | None], ville, formuler) -> str:
        """Cache (`CACHE_TTL_SECONDES`, réponses réussies seulement) + lieu +
        appel Open-Meteo. `formuler(latitude, longitude, nom)` interroge l'API
        et renvoie la phrase ; toute erreur réseau/format devient un message
        (jamais « 0 degré » si un champ manque)."""
        maintenant = time.time()
        en_cache = self._cache.get(cle)
        if en_cache is not None and maintenant - en_cache[0] < CACHE_TTL_SECONDES:
            return en_cache[1]

        lieu = self._lieu(ville)
        if isinstance(lieu, str):
            return lieu
        try:
            resultat = formuler(*lieu)
        except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as exc:
            return f"Erreur en récupérant la météo : {exc!r}"

        self._cache[cle] = (maintenant, resultat)
        return resultat

    @staticmethod
    def _interroger(latitude: float, longitude: float, **params: str | int) -> dict:
        reponse = requests.get(
            FORECAST_URL,
            params={"latitude": latitude, "longitude": longitude, "timezone": "auto", **params},
            timeout=5,
        )
        reponse.raise_for_status()
        return reponse.json()

    def obtenir_meteo(self, ville: str | None = None) -> str:
        """Météo actuelle, en une phrase naturelle (ville par défaut si
        `ville` est omise)."""

        def formuler(latitude: float, longitude: float, nom: str) -> str:
            actuel = self._interroger(
                latitude, longitude,
                current="temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
            )["current"]
            description = DESCRIPTIONS_METEO.get(actuel.get("weather_code"), "des conditions incertaines")
            return (
                f"À {nom}, il fait actuellement {description}, "
                f"{round(actuel['temperature_2m'])} degrés, "
                f"ressenti {round(actuel['apparent_temperature'])} degrés, "
                f"vent de {round(actuel['wind_speed_10m'])} km/h."
            )

        return self._repondre((ville, None), ville, formuler)

    def obtenir_prevision(self, jour: str = "demain", ville: str | None = None) -> str:
        """Prévision de `jour` ("demain" ou "après-demain", sinon demain),
        en une phrase naturelle."""
        jour = jour.strip().lower().replace("apres", "après")
        if jour not in JOURS_PREVISION:
            jour = "demain"

        def formuler(latitude: float, longitude: float, nom: str) -> str:
            journalier = self._interroger(
                latitude, longitude,
                daily="weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                forecast_days=3,
            )["daily"]
            i = JOURS_PREVISION[jour]
            description = DESCRIPTIONS_METEO.get(journalier["weather_code"][i], "des conditions incertaines")
            phrase = (
                f"{jour.capitalize()} à {nom}, on prévoit {description}, "
                f"entre {round(journalier['temperature_2m_min'][i])} et "
                f"{round(journalier['temperature_2m_max'][i])} degrés"
            )
            pluie = journalier.get("precipitation_probability_max", [None] * 3)[i]
            if pluie is not None and pluie >= 20:
                phrase += f", avec {round(pluie)} pour cent de probabilité de précipitations"
            return phrase + "."

        return self._repondre((ville, jour), ville, formuler)

    def executer_outil(self, nom: str, arguments: dict) -> str:
        """Dispatch pour le tool-calling du LLM (même patron que HomeAssistantClient)."""
        ville = arguments.get("ville") or None
        if nom == "obtenir_meteo":
            return self.obtenir_meteo(ville=ville)
        if nom == "obtenir_prevision_meteo":
            return self.obtenir_prevision(jour=arguments.get("jour") or "demain", ville=ville)
        return f"Outil météo inconnu : {nom}"
