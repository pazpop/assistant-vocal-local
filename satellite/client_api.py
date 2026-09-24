"""Client HTTP vers l'API satellite du serveur (voir server/satellite_api.py) :
envoie l'audio enregistré, reçoit la réponse (déjà synthétisée par Piper côté
serveur) à jouer telle quelle."""
import io
import wave

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


def demander(audio: np.ndarray) -> tuple[np.ndarray, int]:
    """Envoie l'audio enregistré au serveur, renvoie sa réponse (audio,
    sample_rate). Lève requests.RequestException si le serveur est
    injoignable, rejette la clé API ou renvoie une erreur — à l'appelant
    (main.py) de décider quoi faire (ex: annoncer l'échec et continuer)."""
    wav = _audio_vers_wav(audio, config.SAMPLE_RATE)
    reponse = requests.post(
        config.SERVER_URL,
        headers={"X-API-Key": config.SERVER_API_KEY},
        files={"audio": ("question.wav", wav, "audio/wav")},
        timeout=config.SERVER_TIMEOUT,
    )
    reponse.raise_for_status()
    return _wav_vers_audio(reponse.content)
