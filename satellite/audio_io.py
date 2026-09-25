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
from dataclasses import dataclass

import numpy as np
import sounddevice as sd

import config

BLOCK_SIZE = 512  # ~32 ms à 16 kHz, cohérent avec la taille de bloc VAD du serveur


@dataclass
class Enregistrement:
    """Résultat de record_until_silence : l'audio et les instants clés, pour
    afficher où passe le temps avant l'envoi au serveur (voir chrono.py)."""

    audio: np.ndarray  # mono float32 [-1, 1], vide si aucune parole n'a démarré
    duree_s: float  # durée totale enregistrée
    debut_parole_s: float  # secondes écoulées avant le premier bloc de parole
    fin_parole_s: float  # instant de fin du dernier bloc de parole
    coupe_par_duree_max: bool  # max_record_seconds atteint sans fin de parole détectée


def _rms(bloc: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(bloc))))


def record_until_silence(debug: bool = False) -> Enregistrement:
    """Enregistre le micro jusqu'à un silence prolongé (ou max_record_seconds).

    `.audio` est un tableau numpy mono float32 normalisé dans [-1, 1] — même
    format que server/audio_io.py — ou un tableau vide si aucune parole n'a
    démarré (permet à l'appelant de distinguer "rien dit" de "a parlé")."""
    sample_rate = config.SAMPLE_RATE
    duree_bloc = BLOCK_SIZE / sample_rate
    silence_blocks_needed = max(1, round(config.SILENCE_DURATION / duree_bloc))
    max_blocks = max(1, round(config.MAX_RECORD_SECONDS / duree_bloc))

    audio_chunks = []
    silence_counter = 0
    speech_started = False
    premier_bloc_parole = 0
    dernier_bloc_parole = 0
    fin_par_silence = False
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
        for indice_bloc in range(max_blocks):
            block = q.get()
            audio_chunks.append(block)

            niveau = _rms(block.flatten())

            if niveau > config.SILENCE_THRESHOLD:
                if not speech_started:
                    premier_bloc_parole = indice_bloc
                speech_started = True
                dernier_bloc_parole = indice_bloc
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
                fin_par_silence = True
                break

    if debug:
        print()

    duree_s = len(audio_chunks) * duree_bloc
    audio = (
        np.concatenate(audio_chunks, axis=0).flatten()
        if audio_chunks and speech_started
        else np.array([], dtype=np.float32)
    )
    return Enregistrement(
        audio=audio,
        duree_s=duree_s,
        debut_parole_s=premier_bloc_parole * duree_bloc,
        fin_parole_s=(dernier_bloc_parole + 1) * duree_bloc,
        coupe_par_duree_max=not fin_par_silence,
    )


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
