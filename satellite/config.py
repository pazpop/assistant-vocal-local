"""Configuration du client satellite (Raspberry Pi) : version allégée de
server/config.py. Seuls le mot-clé, le micro et la connexion au serveur sont
pertinents ici — STT/LLM/TTS/outils restent gérés côté serveur (voir
server/satellite_api.py) : ce client ne fait qu'enregistrer et transmettre.
"""
import sys
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent
_CONFIG_PATH = BASE_DIR / "config.yml"
_EXEMPLE_PATH = BASE_DIR / "config.yml.example"


def _charger_config() -> dict:
    if not _CONFIG_PATH.exists():
        print(
            "\n❌ Fichier de configuration manquant : satellite/config.yml\n\n"
            "Copie le modèle fourni puis adapte les valeurs (adresse du "
            "serveur, clé API...) :\n"
            f"  cp {_EXEMPLE_PATH.name} {_CONFIG_PATH.name}\n"
        )
        sys.exit(1)

    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


_config = _charger_config()


def _get(chemin: str, defaut=None):
    valeur = _config
    for cle in chemin.split("."):
        if not isinstance(valeur, dict) or cle not in valeur:
            return defaut
        valeur = valeur[cle]
    return valeur if valeur is not None else defaut


# Doit rester 16000 : c'est ce que server/stt.py (faster-whisper) attend en
# entrée, quel que soit le matériel du satellite.
SAMPLE_RATE = 16000

# --- Serveur (API satellite, voir server/satellite_api.py) ---
SERVER_URL = _get("server.url", "") or ""
SERVER_API_KEY = _get("server.api_key", "") or ""
SERVER_TIMEOUT = _get("server.timeout", 30)

# --- Zone (nom de la pièce, purement informatif pour l'instant — voir
# ROADMAP.md > Satellites Raspberry Pi > support multi-satellites) ---
ZONE_NAME = _get("zone.name", "") or ""

# --- Mot-clé (openWakeWord) ---
WAKE_WORD_MODEL = _get("wake_word.model", "hey_jarvis")
WAKE_WORD_DISPLAY_NAME = _get("wake_word.display_name", "Hey Jarvis")
WAKE_WORD_THRESHOLD = _get("wake_word.threshold", 0.5)

# --- Audio ---
AUDIO_INPUT_DEVICE = _get("audio.input_device", None)
AUDIO_OUTPUT_DEVICE = _get("audio.output_device", None)
SILENCE_THRESHOLD = _get("audio.silence_threshold", 0.02)
SILENCE_DURATION = _get("audio.silence_duration", 1.0)
MAX_RECORD_SECONDS = _get("audio.max_record_seconds", 15)
NO_SPEECH_TIMEOUT = _get("audio.no_speech_timeout", 8.0)
