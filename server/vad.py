"""Détection d'activité vocale (VAD) en flux, via Silero VAD.

Réutilise le modèle ONNX déjà embarqué avec faster-whisper
(silero_vad_v6.onnx, utilisé normalement pour filtrer les silences après
coup via `vad_filter=True` dans stt.py) : aucune dépendance ni téléchargement
supplémentaire. Ici, on l'utilise en direct, bloc par bloc, pour détecter le
début/fin de parole pendant l'enregistrement d'une question (audio_io.py) —
beaucoup plus robuste au bruit de fond qu'un simple seuil sur le volume
(RMS), et sans calibration manuelle.
"""
import os

import numpy as np
import onnxruntime
from faster_whisper.utils import get_assets_path


class VoiceActivityDetector:
    """VAD Silero en flux : une probabilité de parole par bloc de
    NUM_SAMPLES échantillons, à 16 kHz (config.SAMPLE_RATE), en maintenant
    l'état interne (récurrent) du modèle d'un bloc à l'autre.

    Le modèle est entraîné pour des blocs de 512 échantillons à 16 kHz (32 ms) —
    ces constantes ne sont pas de simples préférences, elles doivent
    correspondre exactement à ce que le modèle attend.
    """

    NUM_SAMPLES = 512
    CONTEXT_SAMPLES = 64

    def __init__(self):
        chemin_modele = os.path.join(get_assets_path(), "silero_vad_v6.onnx")
        options = onnxruntime.SessionOptions()
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 1
        options.log_severity_level = 4
        self._session = onnxruntime.InferenceSession(
            chemin_modele, providers=["CPUExecutionProvider"], sess_options=options
        )
        self.reset()

    def reset(self) -> None:
        """Réinitialise l'état interne (mémoire récurrente + contexte). À
        appeler avant chaque nouvel enregistrement, pour ne pas hériter de
        l'état du précédent."""
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._contexte = np.zeros(self.CONTEXT_SAMPLES, dtype=np.float32)

    def probabilite_parole(self, bloc: np.ndarray) -> float:
        """Probabilité (0-1) que ce bloc de NUM_SAMPLES échantillons (float32
        mono, 16 kHz) contienne de la parole."""
        if bloc.shape[0] != self.NUM_SAMPLES:
            raise ValueError(
                f"Bloc de {self.NUM_SAMPLES} échantillons attendu, reçu {bloc.shape[0]}."
            )

        entree = np.concatenate([self._contexte, bloc]).reshape(1, -1).astype(np.float32)
        sortie, self._h, self._c = self._session.run(
            None, {"input": entree, "h": self._h, "c": self._c}
        )
        self._contexte = bloc[-self.CONTEXT_SAMPLES:]
        return float(np.asarray(sortie).reshape(-1)[0])
