"""Configuration centrale de l'assistant vocal.

Les réglages propres à ton installation (seuils, modèles, ville, jeton Home
Assistant...) vivent dans `config.yml`, à la racine du projet — jamais
commité (voir .gitignore), pour que secrets et préférences personnelles n'y
finissent jamais par erreur. Ce module se contente de le charger et d'exposer
ses valeurs comme attributs (`config.LLM_MODEL`, etc.) : le reste du code
n'a pas besoin de connaître le format du fichier.

Les constantes qui ressemblent davantage à du code qu'à un réglage (gabarit
du prompt système, listes de phrases déclenchant une action) restent ici,
en dur : les éditer via YAML n'apporterait rien de plus qu'éditer ce fichier.
"""
import sys
from pathlib import Path

import yaml

# Racine du projet (un niveau au-dessus de server/), pour que les chemins vers
# models/ et config.yml fonctionnent quel que soit le dossier depuis lequel
# tu lances main.py.
BASE_DIR = Path(__file__).resolve().parent.parent

_CONFIG_PATH = BASE_DIR / "config.yml"
_EXEMPLE_PATH = BASE_DIR / "config.yml.example"


def _charger_config() -> dict:
    """Charge config.yml, ou arrête proprement l'assistant avec des
    instructions claires si le fichier n'existe pas encore."""
    if not _CONFIG_PATH.exists():
        print(
            "\n❌ Fichier de configuration manquant : config.yml\n\n"
            "Ce projet a besoin d'un fichier « config.yml » à la racine "
            "(non commité — il contient tes réglages et secrets personnels, "
            "comme ton jeton Home Assistant).\n\n"
            "Pour le créer :\n"
            f"  1. Copie le modèle fourni :\n"
            f"       PowerShell   : Copy-Item {_EXEMPLE_PATH.name} {_CONFIG_PATH.name}\n"
            f"       macOS/Linux  : cp {_EXEMPLE_PATH.name} {_CONFIG_PATH.name}\n"
            "  2. Ouvre config.yml et adapte les valeurs à ton besoin "
            "(ville, modèle LLM, jeton Home Assistant...).\n"
            "  3. Relance l'assistant.\n"
        )
        sys.exit(1)

    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


_config = _charger_config()


def _get(chemin: str, defaut=None):
    """Lit une valeur imbriquée dans config.yml via un chemin 'a.b.c', avec
    une valeur par défaut si la clé (ou une section) est absente."""
    valeur = _config
    for cle in chemin.split("."):
        if not isinstance(valeur, dict) or cle not in valeur:
            return defaut
        valeur = valeur[cle]
    return valeur if valeur is not None else defaut


# --- Audio ---
SAMPLE_RATE = 16000  # fréquence d'échantillonnage du micro (Hz), pas un réglage utilisateur
VAD_THRESHOLD = _get("audio.vad_threshold", 0.5)
SILENCE_DURATION = _get("audio.silence_duration", 1.0)
MAX_RECORD_SECONDS = _get("audio.max_record_seconds", 15)
# Index (int) ou nom/sous-chaîne (str) du micro à utiliser — voir
# `python -c "import sounddevice as sd; print(sd.query_devices())"`.
# None (valeur par défaut si absent de config.yml) = périphérique par
# défaut de Windows, comportement inchangé.
AUDIO_INPUT_DEVICE = _get("audio.input_device", None)

# --- Conversation continue (enchaîner sans redire "Hey Jarvis") ---
# Délai max sans parole après le mot-clé (un faux déclenchement ne bloque pas le micro)
CONVERSATION_FIRST_TIMEOUT = _get("conversation.first_timeout", 8.0)
CONVERSATION_FOLLOWUP_TIMEOUT = _get("conversation.followup_timeout", 6.0)
# Phrases qui terminent la conversation continue (comparaison en minuscules)
CONVERSATION_END_PHRASES = (
    "merci jarvis",
    "merci, jarvis",
    "merci beaucoup jarvis",
    "c'est tout merci",
    "ce sera tout merci",
    "ça sera tout merci",
)
WAKE_WORD_PROMPT = _get("conversation.wake_word_prompt", "Oui, comment puis-je vous aider ?")
# Nombre d'échanges (question+réponse) gardés dans le contexte envoyé au LLM
# pour cette session — pas de persistance sur disque, l'historique repart à
# zéro à chaque lancement de l'assistant.
CONVERSATION_MAX_ECHANGES = _get("conversation.max_echanges", 20)
# Phrases qui déclenchent un reset vocal de l'historique en cours (comparaison en minuscules ; variantes sans accent listées à la main)
MEMORY_RESET_PHRASES = (
    "oublie tout",
    "oublie tout ce qu'on s'est dit",
    "efface ta mémoire",
    "réinitialise ta mémoire",
    "reinitialise ta memoire",
)
MEMORY_RESET_CONFIRMATION = "D'accord, j'ai oublié tout notre historique de conversation."

# Dès que le LLM décide d'appeler un outil (météo, minuteur, domotique —
# jamais pour une réponse purement conversationnelle), Jarvis dit une de ces
# phrases (choisie au hasard) EN PARALLÈLE de l'appel réseau qui suit, pour
# ne jamais laisser de silence pendant que l'outil travaille.
LLM_TOOL_CALL_PHRASES = (
    "Je vérifie ça.",
    "Un instant.",
    "Je m'en occupe.",
)

# --- Wake word (openWakeWord) ---
WAKE_WORD_MODEL = _get("wake_word.model", "hey_jarvis")
WAKE_WORD_DISPLAY_NAME = _get("wake_word.display_name", "Hey Jarvis")
WAKE_WORD_THRESHOLD = _get("wake_word.threshold", 0.5)

# --- STT (faster-whisper) ---
STT_MODEL_SIZE = _get("stt.model_size", "medium")
STT_DEVICE = _get("stt.device", "cuda")
STT_COMPUTE_TYPE = _get("stt.compute_type", "float16")
STT_LANGUAGE = _get("stt.language", "fr")

# --- LLM (Ollama) ---
LLM_MODEL = _get("llm.model", "qwen2.5:7b")
LLM_KEEP_ALIVE = _get("llm.keep_alive", "30m")  # durée de maintien du modèle en VRAM
LLM_SYSTEM_PROMPT_TEMPLATE = (
    "Tu es un assistant vocal francophone nommé Jarvis, qui tourne entièrement "
    "en local sur ce PC. Adopte un ton chaleureux, amical et enjoué, comme un "
    "ami serviable plutôt qu'un robot froid — sans pour autant rallonger tes "
    "réponses. Réponds toujours de façon concise et naturelle, en 1 à 3 "
    "phrases maximum, car tes réponses seront lues à voix haute.\n\n"
    "Tu peux allumer et éteindre les lumières et prises connectées via les "
    "outils fournis. Voici les appareils disponibles "
    "(identifiant Home Assistant : nom) :\n{appareils}\n"
    "Utilise toujours l'entity_id exact qui correspond le mieux à la demande. "
    "Si aucun appareil ne correspond clairement, demande une précision plutôt "
    "que de deviner.\n\n"
    "Tu peux aussi donner la météo actuelle et la prévision de demain via "
    "les outils fournis, si on te le demande (ex: \"quel temps fait-il\", "
    "\"il pleut dehors ?\", \"quel temps demain ?\").\n\n"
    "Tu peux aussi démarrer un minuteur via l'outil fourni (ex: \"mets un "
    "minuteur de 5 minutes\", \"minuteur de 30 secondes pour les pâtes\"). "
    "Convertis toujours la durée demandée en secondes.\n\n"
    "Tu peux aussi donner la date et l'heure actuelles via l'outil fourni, "
    "si on te le demande (ex: \"quelle heure est-il\", \"on est quel jour ?\")."
)

# --- Météo (Open-Meteo) ---
# Règle uniforme pour tous les modules optionnels de ce fichier : absent de
# config.yml = désactivé. Il faut un "enabled: true" explicite pour
# activer, jamais une déduction à partir d'un autre réglage.
WEATHER_ENABLED = _get("weather.enabled", False)

# --- Localisation (partagée par la météo ET la date/heure, pour rester
# cohérentes : les deux doivent parler de la même région) ---
LOCATION_CITY = _get("location.city", "Montréal")
LOCATION_GEOCODE_QUERY = _get("location.geocode_query", "Montréal, QC")
LOCATION_TIMEZONE = _get("location.timezone", "America/Toronto")

# --- Home Assistant (VM sur ton réseau local, sans dépendance cloud) ---
HA_BASE_URL = _get("home_assistant.base_url", "")
HA_VERIFY_SSL = _get("home_assistant.verify_ssl", True)
HA_TOKEN = _get("home_assistant.token", "") or ""
HA_DEVICE_ALIASES: dict[str, str] = _get("home_assistant.device_aliases", {}) or {}
# Absent de config.yml = désactivé, même si "token" est rempli — voir
# WEATHER_ENABLED ci-dessus pour la règle uniforme.
HA_ENABLED = _get("home_assistant.enabled", False)

# --- Alertes météo publiques (Environnement Canada, flux Atom gratuit) ---
ALERTS_FEED_URL = _get("alerts.feed_url", "") or ""
# Absent de config.yml = désactivé, même si "feed_url" est rempli — voir
# WEATHER_ENABLED ci-dessus pour la règle uniforme.
ALERTS_ENABLED = _get("alerts.enabled", False)
# Intervalle entre deux sondages en arrière-plan (minutes). 0 = pas de
# sondage automatique, seulement à la demande.
ALERTS_CHECK_INTERVAL_MINUTES = _get("alerts.check_interval_minutes", 15)
# Période (heure locale, "HH:MM") pendant laquelle l'annonce PROACTIVE d'une
# nouvelle alerte est coupée, pour ne jamais réveiller personne la nuit — une
# alerte qui apparaît dans cette période est ignorée (pas rattrapée après
# coup) : seule une alerte réellement nouvelle après la fin de la coupure est
# annoncée. Sans effet sur une question posée explicitement à voix haute, à
# toute heure. Mets les deux valeurs identiques pour désactiver cette
# coupure (annonce à toute heure).
ALERTS_QUIET_HOURS_START = _get("alerts.quiet_hours_start", "22:00")
ALERTS_QUIET_HOURS_END = _get("alerts.quiet_hours_end", "08:00")

# --- Panneau de ressources local (dashboard.py) ---
DASHBOARD_ENABLED = _get("dashboard.enabled", False)
DASHBOARD_PORT = _get("dashboard.port", 8790)

# --- Open WebUI (lancé optionnellement par launch.py, dans son propre venv
# séparé — voir ARCHITECTURE.md) ---
OPEN_WEBUI_ENABLED = _get("open_webui.enabled", False)
OPEN_WEBUI_HOST = _get("open_webui.host", "127.0.0.1")
OPEN_WEBUI_PORT = _get("open_webui.port", 3000)
# Clé API (Réglages > Compte > Clés API dans Open WebUI), uniquement pour
# `launch.py --purge-webui-memory` — sans effet sur le fonctionnement normal.
OPEN_WEBUI_API_KEY = _get("open_webui.api_key", "") or ""

# --- TTS (Piper — OHF-Voice/piper1-gpl, GPL-3.0 depuis la migration oct. 2025) ---
TTS_VOICE_MODEL = str(BASE_DIR / _get("tts.voice_model", "models/piper/fr_FR-tom-medium.onnx"))
TTS_USE_CUDA = _get("tts.use_cuda", False)
# Uniquement pour une voix multi-locuteurs (ex: mls) : lequel des locuteurs
# utiliser. Sans effet sur une voix mono-locuteur (siwis, tom...).
TTS_SPEAKER_ID = _get("tts.speaker_id", None)

# --- Vérification de version (lancée uniquement par launch.py) ---
UPDATE_CHECK_ENABLED = _get("update_check.enabled", False)

# --- API satellite (voir ROADMAP.md > Satellites Raspberry Pi) : écoute au-delà
# de 127.0.0.1 par défaut (0.0.0.0), donc toujours protégée par une clé API,
# contrairement au panneau de ressources ou à Open WebUI en local. ---
SATELLITE_ENABLED = _get("satellite.enabled", False)
SATELLITE_HOST = _get("satellite.host", "0.0.0.0")
SATELLITE_PORT = _get("satellite.port", 8791)
SATELLITE_API_KEY = _get("satellite.api_key", "") or ""
