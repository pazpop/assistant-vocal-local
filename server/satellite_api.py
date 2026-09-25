"""API réseau pour les satellites (Raspberry Pi, voir ROADMAP.md > Satellites
Raspberry Pi) : un satellite envoie sa question en audio et joue la réponse.

`POST /assistant` : corps = WAV brut (mono, 16 bits, config.SAMPLE_RATE — le
format que record_until_silence produit), en-tête `X-Zone` = nom du satellite
(sert à lui renvoyer ses minuteurs). Réponse EN FLUX, phrase par phrase :
chaque phrase est synthétisée dès qu'elle est complète dans le flux du LLM,
puis envoyée aussitôt (même principe que main.parler_en_flux). Tout le
pipeline (STT -> LLM/outils -> TTS) tourne ici : le satellite n'a besoin que
d'un micro et d'un haut-parleur.

`GET /notifications` : sons en attente pour ce satellite (minuteur terminé...).
Un satellite n'accepte pas de connexion entrante : il vient les chercher.

Format des réponses audio : une suite de trames, chacune = 4 octets (entier
big-endian non signé : taille N) suivis de N octets d'un WAV mono 16 bits
complet (qui porte sa propre fréquence d'échantillonnage). Fin de flux = fin
de la connexion.

Toujours protégée par une clé API (`X-API-Key`), vérifiée AVANT de lire le
corps. HTTP en clair : à réserver à un réseau de confiance (ou à placer
derrière WireGuard/Tailscale/un proxy TLS). Cette API écoute au-delà de
127.0.0.1 par défaut (satellite.host) pour être joignable depuis un autre
appareil du réseau local.
"""
import io
import secrets
import struct
import threading
import time
import wave
from collections import deque
from typing import Callable, Iterable, Iterator

import numpy as np
import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response, StreamingResponse

import config
from phrases import decouper_en_phrases

INCOMPREHENSION = "Désolé, je n'ai pas compris."

CLE_API_LONGUEUR_MIN = 16
DUREE_MAX_QUESTION_S = 60  # bien au-dessus des 15 s de satellite.max_record_seconds
TAILLE_MAX_QUESTION = DUREE_MAX_QUESTION_S * config.SAMPLE_RATE * 2 + 1024
NOTIFICATIONS_MAX_PAR_ZONE = 20
ZONE_PAR_DEFAUT = "satellite"


class WavInvalide(ValueError):
    """Le WAV reçu n'est pas au format attendu (mono, 16 bits, config.SAMPLE_RATE)."""


def _cle_api_valide(fournie: str) -> bool:
    """True seulement si satellite.api_key est renseignée ET correspond —
    une clé vide dans config.yml désactive l'accès plutôt que de l'ouvrir à
    n'importe qui. Comparaison à temps constant, sur des octets (compare_digest
    refuse les `str` non ASCII)."""
    return bool(config.SATELLITE_API_KEY) and secrets.compare_digest(
        fournie.encode(), config.SATELLITE_API_KEY.encode()
    )


def _wav_vers_audio(donnees: bytes) -> np.ndarray:
    """Décode le WAV d'une question en float32 [-1, 1], le format attendu par
    SpeechToText.transcribe. Lève WavInvalide si le format n'est pas celui
    que record_until_silence produit : sinon Whisper transcrirait du bruit."""
    try:
        with wave.open(io.BytesIO(donnees), "rb") as f:
            if (f.getnchannels(), f.getsampwidth(), f.getframerate()) != (1, 2, config.SAMPLE_RATE):
                raise WavInvalide(f"attendu : mono, 16 bits, {config.SAMPLE_RATE} Hz")
            if f.getnframes() > DUREE_MAX_QUESTION_S * config.SAMPLE_RATE:
                raise WavInvalide(f"plus de {DUREE_MAX_QUESTION_S} s d'audio")
            brut = f.readframes(f.getnframes())
    except (wave.Error, EOFError) as exc:
        raise WavInvalide(str(exc)) from exc
    return np.frombuffer(brut, dtype=np.int16).astype(np.float32) / 32768.0


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
    try:
        for phrase in decouper_en_phrases(fragments):
            audio = tts.synthesize(phrase)
            if audio.size:
                yield _trame(_audio_vers_wav(audio, tts.sample_rate))
    except Exception as exc:  # noqa: BLE001 - le flux est déjà commencé : on journalise, le client verra la coupure
        print(f"[erreur] API satellite, réponse interrompue : {exc!r}")
        raise


class BoiteNotifications:
    """Sons à livrer à un satellite (minuteur terminé...), par zone. Le
    satellite les récupère avec `GET /notifications` ; au-delà de
    NOTIFICATIONS_MAX_PAR_ZONE, les plus anciennes sont abandonnées."""

    def __init__(self) -> None:
        self._verrou = threading.Lock()
        self._par_zone: dict[str, deque[bytes]] = {}

    def deposer(self, zone: str, audio: np.ndarray, sample_rate: int) -> None:
        trame = _trame(_audio_vers_wav(audio, sample_rate))
        with self._verrou:
            self._par_zone.setdefault(zone, deque(maxlen=NOTIFICATIONS_MAX_PAR_ZONE)).append(trame)

    def retirer(self, zone: str) -> bytes:
        """Toutes les trames en attente pour `zone` (b"" s'il n'y en a pas)."""
        with self._verrou:
            return b"".join(self._par_zone.pop(zone, ()))


def _zone(x_zone: str) -> str:
    return x_zone.strip()[:64] or ZONE_PAR_DEFAUT


async def _lire_corps(request: Request) -> bytes:
    """Lit le corps de la requête en refusant plus de TAILLE_MAX_QUESTION
    octets (413), sans jamais tout charger avant de connaître la taille."""
    declare = request.headers.get("content-length", "")
    if declare.isdigit() and int(declare) > TAILLE_MAX_QUESTION:
        raise HTTPException(status_code=413, detail="Audio trop volumineux.")
    morceaux: list[bytes] = []
    total = 0
    async for morceau in request.stream():
        total += len(morceau)
        if total > TAILLE_MAX_QUESTION:
            raise HTTPException(status_code=413, detail="Audio trop volumineux.")
        morceaux.append(morceau)
    return b"".join(morceaux)


def _verifier_cle(x_api_key: str) -> None:
    if not _cle_api_valide(x_api_key):
        raise HTTPException(status_code=401, detail="Clé API invalide ou manquante.")


def creer_app(
    stt,
    tts,
    repondre_flux: Callable[[str, str], Iterable[str]],
    boite: BoiteNotifications,
) -> FastAPI:
    """`repondre_flux(question, zone)` vient de main.py : mêmes outils (météo,
    domotique, minuteur...) et même historique de conversation que la boucle
    micro locale — un satellite est une autre façon de parler à Jarvis, pas
    une seconde instance."""
    app = FastAPI(title="Jarvis Satellite API")

    @app.post("/assistant")
    async def assistant(
        request: Request, x_api_key: str = Header(default=""), x_zone: str = Header(default="")
    ) -> StreamingResponse:
        _verifier_cle(x_api_key)
        try:
            signal = _wav_vers_audio(await _lire_corps(request))
        except WavInvalide as exc:
            raise HTTPException(status_code=400, detail=f"WAV invalide : {exc}") from exc

        # Transcription bloquante : hors de la boucle d'événements, sinon
        # toutes les autres requêtes attendent pendant qu'elle tourne.
        question = await run_in_threadpool(stt.transcribe, signal)
        fragments = repondre_flux(question, _zone(x_zone)) if question else [INCOMPREHENSION]

        return StreamingResponse(
            _trames_reponse(tts, fragments), media_type="application/octet-stream"
        )

    @app.get("/notifications")
    async def notifications(
        x_api_key: str = Header(default=""), x_zone: str = Header(default="")
    ) -> Response:
        _verifier_cle(x_api_key)
        return Response(boite.retirer(_zone(x_zone)), media_type="application/octet-stream")

    return app


def demarrer(stt, tts, repondre_flux, boite: BoiteNotifications) -> str:
    """Lance l'API dans un thread à part (démon), retourne son URL. Lève
    RuntimeError si elle n'a pas démarré (ex: port déjà pris)."""
    app = creer_app(stt, tts, repondre_flux, boite)
    conf = uvicorn.Config(
        app, host=config.SATELLITE_HOST, port=config.SATELLITE_PORT, log_level="warning"
    )
    serveur = uvicorn.Server(conf)
    fil = threading.Thread(target=serveur.run, daemon=True)
    fil.start()
    for _ in range(50):  # jusqu'à 5 s
        if serveur.started or not fil.is_alive():
            break
        time.sleep(0.1)
    if not serveur.started:
        raise RuntimeError(f"le port {config.SATELLITE_PORT} est peut-être déjà utilisé")
    # 0.0.0.0 n'est pas une adresse joignable : c'est celle du PC qu'il faut donner au satellite.
    hote = "<IP-de-ce-PC>" if config.SATELLITE_HOST == "0.0.0.0" else config.SATELLITE_HOST
    return f"http://{hote}:{config.SATELLITE_PORT}/assistant"
