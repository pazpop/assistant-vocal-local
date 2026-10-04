"""Gestion de l'audio : capture micro (avec détection de silence via VAD) et lecture."""
import queue
import threading

import numpy as np
import sounddevice as sd

import config
from vad import VoiceActivityDetector

# Sérialise toute lecture audio : sans ça, l'annonce de fin d'un minuteur
# (déclenchée dans son propre thread) pourrait se jouer par-dessus une
# réponse de Jarvis en cours. Avec ce verrou, l'un attend simplement que
# l'autre ait fini de parler.
_verrou_lecture = threading.Lock()


def record_until_silence(
    vad: VoiceActivityDetector,
    sample_rate: int = config.SAMPLE_RATE,
    vad_threshold: float = config.VAD_THRESHOLD,
    silence_duration: float = config.SILENCE_DURATION,
    max_duration: float = config.MAX_RECORD_SECONDS,
    no_speech_timeout: float | None = None,
    debug: bool = False,
) -> np.ndarray:
    """Enregistre le micro jusqu'à un silence prolongé (ou max_duration).

    Retourne un tableau numpy mono float32 normalisé dans [-1, 1],
    prêt à être passé à faster-whisper. Si aucune parole n'a jamais démarré
    (juste du silence), retourne un tableau vide plutôt que le silence
    capturé — permet à l'appelant de distinguer "rien dit" de "a parlé".

    Le début et la fin de parole sont détectés via `vad` (VoiceActivityDetector,
    voir vad.py) plutôt qu'un simple seuil sur le volume : robuste au bruit
    de fond, sans calibration manuelle. `vad` doit être créé une seule fois
    (chargement du modèle ONNX) et réutilisé d'un appel à l'autre ; il est
    réinitialisé (état interne remis à zéro) à chaque appel de cette fonction.

    `no_speech_timeout`, si fourni, abandonne l'écoute (retourne un tableau
    vide) si aucune parole n'a démarré après ce délai — plus court que
    `max_duration`, pensé pour la conversation continue : après une réponse
    de Jarvis, on n'attend pas 15s avant de repasser en veille si personne
    n'enchaîne.

    En mode debug, affiche la probabilité de parole (VAD) en continu.
    """
    block_size = vad.NUM_SAMPLES  # imposé par le modèle VAD (512 échantillons, 32 ms à 16 kHz)
    duree_bloc = block_size / sample_rate
    silence_blocks_needed = max(1, round(silence_duration / duree_bloc))
    max_blocks = max(1, round(max_duration / duree_bloc))
    no_speech_blocks = (
        max(1, round(no_speech_timeout / duree_bloc)) if no_speech_timeout else None
    )

    vad.reset()
    audio_chunks = []
    silence_counter = 0
    blocs_sans_parole = 0
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
        blocksize=block_size,
        callback=callback,
        device=config.AUDIO_INPUT_DEVICE,
    ):
        for _ in range(max_blocks):
            block = q.get()
            audio_chunks.append(block)

            proba = vad.probabilite_parole(block.flatten())

            if proba > vad_threshold:
                speech_started = True
                silence_counter = 0
            elif speech_started:
                silence_counter += 1
            else:
                blocs_sans_parole += 1

            if debug:
                etat = "parole" if proba > vad_threshold else "silence"
                print(
                    f"\r[audio] vad={proba:.3f}  seuil={vad_threshold:.2f}  "
                    f"({etat}, {silence_counter}/{silence_blocks_needed})   ",
                    end="",
                    flush=True,
                )

            if speech_started and silence_counter >= silence_blocks_needed:
                break

            if no_speech_blocks is not None and blocs_sans_parole >= no_speech_blocks:
                break

    if debug:
        print()

    if not audio_chunks or not speech_started:
        return np.array([], dtype=np.float32)

    return np.concatenate(audio_chunks, axis=0).flatten()


def play_audio(audio: np.ndarray, sample_rate: int) -> None:
    """Joue un signal audio sur les haut-parleurs par défaut (bloquant)."""
    if audio.size == 0:
        return
    with _verrou_lecture:
        sd.play(audio, samplerate=sample_rate)
        sd.wait()
