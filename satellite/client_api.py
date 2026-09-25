"""Client HTTP vers l'API satellite du serveur (voir server/satellite_api.py) :
envoie l'audio enregistré, reçoit la réponse (déjà synthétisée par Piper côté
serveur) phrase par phrase, chacune à jouer dès qu'elle arrive."""
import io
import struct
import time
import wave
from typing import Callable, Iterable, Iterator

import numpy as np
import requests

import config


def _audio_vers_wav(audio: np.ndarray, sample_rate: int) -> bytes:
    """Encode un signal float32 [-1, 1] en WAV mono 16 bits — le format
    attendu par server/satellite_api.py en entrée."""
    audio_int16 = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    tampon = io.BytesIO()
    with wave.open(tampon, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        f.writeframes(audio_int16.tobytes())
    return tampon.getvalue()


def _wav_vers_audio(donnees: bytes) -> tuple[np.ndarray, int]:
    """Décode un WAV mono 16 bits en float32 [-1, 1] + sa fréquence
    d'échantillonnage — la réponse du serveur (voix Piper) n'est pas
    forcément à 16 kHz, contrairement à l'audio envoyé."""
    with wave.open(io.BytesIO(donnees), "rb") as f:
        sample_rate = f.getframerate()
        brut = f.readframes(f.getnframes())
    audio_int16 = np.frombuffer(brut, dtype=np.int16)
    return audio_int16.astype(np.float32) / 32768.0, sample_rate


def _extraire_trames(morceaux: Iterable[bytes]) -> Iterator[bytes]:
    """Reconstitue les WAV (un par phrase) à partir des morceaux d'octets qui
    arrivent du réseau, découpés n'importe où : chaque trame est un entier
    big-endian de 4 octets (taille N) suivi de N octets de WAV — le format
    produit par server/satellite_api.py (_trame). Chaque WAV est produit dès
    qu'il est complet, sans attendre la fin du flux."""
    tampon = bytearray()
    for morceau in morceaux:
        tampon.extend(morceau)
        while len(tampon) >= 4:
            (taille,) = struct.unpack(">I", tampon[:4])
            if len(tampon) < 4 + taille:
                break
            yield bytes(tampon[4 : 4 + taille])
            del tampon[: 4 + taille]

    if tampon:
        raise requests.exceptions.ChunkedEncodingError(
            "Flux interrompu au milieu d'une phrase de la réponse."
        )


def demander(
    audio: np.ndarray, signaler: Callable[..., None] = lambda etape, **infos: None
) -> Iterator[tuple[np.ndarray, int]]:
    """Envoie l'audio enregistré au serveur, puis produit (audio, sample_rate)
    pour chaque phrase de la réponse, dès qu'elle arrive : à l'appelant
    (main.py) de la jouer pendant que le serveur prépare la suite. Lève
    requests.RequestException (à l'itération, pas à l'appel) si le serveur est
    injoignable, rejette la clé API, renvoie une erreur ou coupe le flux en
    cours de route — à l'appelant de décider quoi faire (ex: annoncer l'échec
    et continuer).

    `signaler(etape, **infos)` est appelé à chaque étape (wav_cree, envoi,
    transcription_finie, premiere_phrase — voir chrono.formater_etape) pour
    montrer où passe le temps.

    Le serveur envoie les en-têtes de sa réponse dès que la transcription est
    faite (avant même que le LLM ait commencé) : requests.post(stream=True)
    rend la main à ce moment-là, ce qui donne la durée envoi + transcription."""
    debut_encodage = time.perf_counter()
    wav = _audio_vers_wav(audio, config.SAMPLE_RATE)
    signaler(
        "wav_cree",
        duree_audio=audio.size / config.SAMPLE_RATE,
        octets=len(wav),
        duree_encodage=time.perf_counter() - debut_encodage,
    )

    signaler("envoi")
    instant_envoi = time.perf_counter()
    with requests.post(
        config.SERVER_URL,
        headers={"X-API-Key": config.SERVER_API_KEY},
        files={"audio": ("question.wav", wav, "audio/wav")},
        timeout=config.SERVER_TIMEOUT,
        stream=True,
    ) as reponse:
        reponse.raise_for_status()
        instant_transcription = time.perf_counter()
        signaler("transcription_finie", depuis_envoi=instant_transcription - instant_envoi)

        premiere = True
        for wav_phrase in _extraire_trames(reponse.iter_content(chunk_size=None)):
            if premiere:
                maintenant = time.perf_counter()
                signaler(
                    "premiere_phrase",
                    depuis_envoi=maintenant - instant_envoi,
                    depuis_transcription=maintenant - instant_transcription,
                )
                premiere = False
            yield _wav_vers_audio(wav_phrase)
