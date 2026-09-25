"""API réseau pour un futur client satellite (Raspberry Pi, voir
ROADMAP.md > Satellites Raspberry Pi).

Un seul endpoint REST (`POST /assistant`) : le satellite envoie un WAV (mono,
16 bits, échantillonné à config.SAMPLE_RATE — même format que record_until_
silence produit) et reçoit la réponse EN FLUX, phrase par phrase : chaque
phrase est synthétisée dès qu'elle est complète dans le flux du LLM, puis
envoyée aussitôt, pour que le satellite commence à parler avant la fin de la
génération (même principe que la boucle micro locale, voir main.
parler_en_flux). Tout le pipeline (STT -> LLM/outils -> TTS) tourne ici, sur
le PC : le satellite n'a besoin que d'un micro/haut-parleur, pas de GPU ni de
modèles chargés localement.

Format de la réponse : une suite de trames, chacune = 4 octets (entier
big-endian non signé : taille N) suivis de N octets d'un WAV mono 16 bits
complet (qui porte donc sa propre fréquence d'échantillonnage). Fin de flux =
fin de la connexion.

Toujours protégée par une clé API (X-API-Key) : contrairement au panneau de
ressources ou à Home Assistant, cette API écoute au-delà de 127.0.0.1 par
défaut (satellite.host, voir config.py) pour être joignable depuis un autre
appareil du réseau local.
"""
import io
import secrets
import struct
import threading
import wave
from typing import Iterable, Iterator

import numpy as np
import uvicorn
from fastapi import FastAPI, Header, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

import config
from phrases import decouper_en_phrases

INCOMPREHENSION = "Désolé, je n'ai pas compris."


def _cle_api_valide(fournie: str) -> bool:
    """True seulement si satellite.api_key est renseignée ET correspond —
    une clé vide dans config.yml désactive l'accès plutôt que de l'ouvrir à
    n'importe qui (voir la note dans config.yml.example). Comparaison à
    temps constant (compare_digest) : une simple égalité de chaînes fuite le
    nombre de caractères corrects via le temps de réponse."""
    return bool(config.SATELLITE_API_KEY) and secrets.compare_digest(
        fournie, config.SATELLITE_API_KEY
    )


def _wav_vers_audio(donnees: bytes) -> np.ndarray:
    """Décode un WAV mono 16 bits en float32 [-1, 1], le format attendu par
    SpeechToText.transcribe (voir stt.py)."""
    with wave.open(io.BytesIO(donnees), "rb") as f:
        brut = f.readframes(f.getnframes())
    audio_int16 = np.frombuffer(brut, dtype=np.int16)
    return audio_int16.astype(np.float32) / 32768.0


def _audio_vers_wav(audio: np.ndarray, sample_rate: int) -> bytes:
    """Encode un signal float32 [-1, 1] (sortie de TextToSpeech.synthesize)
    en WAV mono 16 bits."""
    audio_int16 = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    tampon = io.BytesIO()
    with wave.open(tampon, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        f.writeframes(audio_int16.tobytes())
    return tampon.getvalue()


def _trame(wav: bytes) -> bytes:
    """Préfixe un WAV de sa taille (4 octets big-endian) : le satellite sait
    ainsi où finit chaque phrase dans le flux (voir satellite/client_api.py)."""
    return struct.pack(">I", len(wav)) + wav


def _trames_reponse(tts, fragments: Iterable[str]) -> Iterator[bytes]:
    """Produit une trame par phrase du flux de texte, synthétisée au fil de
    l'eau. Générateur synchrone : Starlette l'itère dans un thread à part, ce
    qui laisse la boucle d'événements libre pendant que le LLM et Piper
    travaillent."""
    for phrase in decouper_en_phrases(fragments):
        audio = tts.synthesize(phrase)
        if audio.size:
            yield _trame(_audio_vers_wav(audio, tts.sample_rate))


def creer_app(stt, tts, repondre_flux) -> FastAPI:
    """`repondre_flux(question: str) -> Iterator[str]` vient de main.py (voir
    choisir_reponse) : mêmes outils (météo, domotique, minuteur...) et même
    historique de conversation que la boucle micro locale — un satellite est
    une autre façon de parler à Jarvis, pas une seconde instance."""
    app = FastAPI(title="Jarvis Satellite API")

    @app.post("/assistant")
    async def assistant(
        audio: UploadFile, x_api_key: str = Header(default="")
    ) -> StreamingResponse:
        if not _cle_api_valide(x_api_key):
            raise HTTPException(status_code=401, detail="Clé API invalide ou manquante.")

        signal = _wav_vers_audio(await audio.read())
        question = stt.transcribe(signal)
        fragments = repondre_flux(question) if question else [INCOMPREHENSION]

        return StreamingResponse(
            _trames_reponse(tts, fragments), media_type="application/octet-stream"
        )

    return app


def demarrer(stt, tts, repondre_flux) -> str:
    """Lance l'API dans un thread à part (démon), retourne son URL."""
    app = creer_app(stt, tts, repondre_flux)
    conf = uvicorn.Config(
        app, host=config.SATELLITE_HOST, port=config.SATELLITE_PORT, log_level="warning"
    )
    serveur = uvicorn.Server(conf)
    threading.Thread(target=serveur.run, daemon=True).start()
    return f"http://{config.SATELLITE_HOST}:{config.SATELLITE_PORT}/assistant"
