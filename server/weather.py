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

# Outil exposé au LLM (même format que HA_TOOLS dans home_assistant.py).
WEATHER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "obtenir_meteo",
            "description": (
                "Donne la météo actuelle (conditions, température, ressenti, "
                "vent). Appelle TOUJOURS cet outil pour toute question sur le "
                "temps qu'il fait. Omets le paramètre 'ville' si aucune ville "
                "n'est explicitement nommée dans la question : l'outil "
                "connaît déjà la ville de l'utilisateur par défaut, ne "
                "demande jamais à l'utilisateur où il se trouve."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ville": {
                        "type": "string",
                        "description": (
                            "Ville pour laquelle donner la météo, seulement "
                            "si explicitement nommée dans la question (ex: "
                            "\"quel temps fait-il à Paris ?\")."
                        ),
                    },
                },
                "required": [],
            },
        },
    },
]

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
    "quel temps fait",
    "quel temps qu'il fait",
    "quel temps il fait",
    "temps qu'il fait dehors",
    "fait-il dehors",
)


def demande_meteo(texte: str) -> bool:
    """Détecte si une phrase transcrite demande la météo."""
    return contient_une_phrase(texte, WEATHER_TRIGGER_PHRASES)


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
        # Une entrée par ville demandée (clé = paramètre `ville` reçu, None
        # pour la ville par défaut) : {ville: (timestamp, réponse formatée)}.
        self._cache: dict[str | None, tuple[float, str]] = {}

    def obtenir_meteo(self, ville: str | None = None) -> str:
        """Récupère la météo actuelle et la formule en une phrase naturelle.

        Sans `ville`, utilise la position de l'utilisateur (mise en cache
        au démarrage). Avec `ville`, géocode cette ville à la volée pour
        répondre à une question météo sur un autre lieu — un échec de
        géocodage ici ne désactive pas la météo pour autant, contrairement à
        un échec au démarrage.

        Une réponse déjà obtenue pour la même ville dans les
        `CACHE_TTL_SECONDES` dernières secondes est réutilisée telle quelle,
        sans nouvel appel réseau (ni géocodage, ni prévisions) — seules les
        réponses réussies sont mises en cache, jamais un message d'erreur."""
        maintenant = time.time()
        en_cache = self._cache.get(ville)
        if en_cache is not None and maintenant - en_cache[0] < CACHE_TTL_SECONDES:
            return en_cache[1]

        if ville is None:
            latitude, longitude, nom = self.latitude, self.longitude, self.ville
        else:
            try:
                latitude, longitude, _ = geocoder(ville)
            except RuntimeError:
                return (
                    f"Je n'ai pas trouvé la ville « {ville} ». Je ne peux "
                    f"donner la météo que pour {self.ville} pour l'instant."
                )
            nom = ville

        try:
            reponse = requests.get(
                FORECAST_URL,
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
                    "timezone": "auto",
                },
                timeout=5,
            )
            reponse.raise_for_status()
        except requests.RequestException as exc:
            return f"Erreur en récupérant la météo : {exc}"

        actuel = reponse.json().get("current", {})
        temperature = round(actuel.get("temperature_2m", 0))
        ressenti = round(actuel.get("apparent_temperature", 0))
        vent = round(actuel.get("wind_speed_10m", 0))
        code = actuel.get("weather_code")
        description = DESCRIPTIONS_METEO.get(code, "des conditions incertaines")

        resultat = (
            f"À {nom}, il fait actuellement {description}, "
            f"{temperature} degrés, ressenti {ressenti} degrés, "
            f"vent de {vent} km/h."
        )
        self._cache[ville] = (maintenant, resultat)
        return resultat

    def executer_outil(self, nom: str, arguments: dict) -> str:
        """Dispatch pour le tool-calling du LLM (même patron que HomeAssistantClient)."""
        if nom == "obtenir_meteo":
            return self.obtenir_meteo(ville=arguments.get("ville") or None)
        return f"Outil météo inconnu : {nom}"
