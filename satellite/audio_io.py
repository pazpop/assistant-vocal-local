"""Capture micro et lecture haut-parleur pour le client satellite.

Détection de fin de parole par simple seuil de volume (RMS), pas par VAD
Silero comme le serveur (server/vad.py) : ce modèle est normalement récupéré
depuis l'installation de faster-whisper (get_assets_path()), qui n'a aucune
raison d'être installée sur le satellite (STT reste géré côté serveur, voir
server/satellite_api.py). Le paquet silero-vad sur PyPI dépend de PyTorch
même pour son mode ONNX — bien trop lourd sur un Raspberry Pi juste pour
détecter un silence. Un seuil RMS est moins robuste au bruit de fond que le
VAD du serveur, mais suffisant pour un satellite dans une pièce calme —
limite connue, pas un oubli (voir ARCHITECTURE.md).
"""
import queue

import numpy as np
import sounddevice as sd

import config

BLOCK_SIZE = 512  # ~32 ms à 16 kHz, cohérent avec la taille de bloc VAD du serveur


def _rms(bloc: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(bloc))))


def record_until_silence(debug: bool = False) -> np.ndarray:
    """Enregistre le micro jusqu'à un silence prolongé (ou max_record_seconds).

    Retourne un tableau numpy mono float32 normalisé dans [-1, 1] — même
    format que server/audio_io.py — ou un tableau vide si aucune parole n'a
    démarré (permet à l'appelant de distinguer "rien dit" de "a parlé")."""
    sample_rate = config.SAMPLE_RATE
    duree_bloc = BLOCK_SIZE / sample_rate
    silence_blocks_needed = max(1, round(config.SILENCE_DURATION / duree_bloc))
    max_blocks = max(1, round(config.MAX_RECORD_SECONDS / duree_bloc))

    audio_chunks = []
    silence_counter = 0
    speech_started = False
    q: "queue.Queue[np.ndarray]" = queue.Queue()

    def callback(indata, frames, time_info, status):
        if status:
            print(f"[audio_io] status: {status}")
        q.put(indata.copy())

    with sd.InputStream(
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        blocksize=BLOCK_SIZE,
        callback=callback,
        device=config.AUDIO_INPUT_DEVICE,
    ):
        for _ in range(max_blocks):
            block = q.get()
            audio_chunks.append(block)

            niveau = _rms(block.flatten())

            if niveau > config.SILENCE_THRESHOLD:
                speech_started = True
                silence_counter = 0
            elif speech_started:
                silence_counter += 1

            if debug:
                etat = "parole" if niveau > config.SILENCE_THRESHOLD else "silence"
                print(
                    f"\r[audio] niveau={niveau:.3f}  seuil={config.SILENCE_THRESHOLD:.3f}  "
                    f"({etat}, {silence_counter}/{silence_blocks_needed})   ",
                    end="",
                    flush=True,
                )

            if speech_started and silence_counter >= silence_blocks_needed:
                break

    if debug:
        print()

    if not audio_chunks or not speech_started:
        return np.array([], dtype=np.float32)

    return np.concatenate(audio_chunks, axis=0).flatten()


def play_audio(audio: np.ndarray, sample_rate: int) -> None:
    """Joue un signal audio sur le haut-parleur configuré (bloquant)."""
    if audio.size == 0:
        return
    sd.play(audio, samplerate=sample_rate, device=config.AUDIO_OUTPUT_DEVICE)
    sd.wait()


def generer_bip(sample_rate: int, frequence: float = 880.0, duree: float = 0.15) -> np.ndarray:
    """Court bip sinusoïdal joué dès le mot-clé détecté, pour confirmer que
    le satellite écoute — pas de TTS local pour dire une phrase comme le fait
    le serveur (voir main.py), donc un simple signal sonore à la place."""
    t = np.linspace(0, duree, int(sample_rate * duree), endpoint=False)
    return (0.3 * np.sin(2 * np.pi * frequence * t)).astype(np.float32)
