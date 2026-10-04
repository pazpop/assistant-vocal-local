"""Reconnaissance vocale (Speech-to-Text) avec faster-whisper."""
import os
import sys
import threading
from pathlib import Path

import numpy as np

# Sous Windows, les DLL CUDA installées via pip (nvidia-cublas-cu12,
# nvidia-cudnn-cu12) atterrissent dans site-packages/nvidia/*/bin, un
# dossier que le chargeur de DLL de Windows ne scanne pas par défaut
# (contrairement à Linux). Sans ça, ctranslate2 échoue à charger
# cublas64_12.dll/cudnn64_9.dll au moment d'utiliser device="cuda".
# `os.add_dll_directory` ne suffit pas ici : ctranslate2 résout les DLL
# CUDA en cascade (cublas -> cublasLt, cudnn -> ses sous-modules) via le
# PATH, pas via les répertoires enregistrés par cette API. Il faut donc
# bien ajouter ces dossiers au PATH du processus.
if sys.platform == "win32":
    _nvidia_dir = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    if _nvidia_dir.is_dir():
        _bin_dirs = [str(p) for p in _nvidia_dir.glob("*/bin")]
        os.environ["PATH"] = os.pathsep.join(_bin_dirs + [os.environ.get("PATH", "")])

from faster_whisper import WhisperModel

import config


class SpeechToText:
    def __init__(
        self,
        model_size: str = config.STT_MODEL_SIZE,
        device: str = config.STT_DEVICE,
        compute_type: str = config.STT_COMPUTE_TYPE,
    ):
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)
        # Micro local et satellites transcrivent depuis des threads différents.
        self._verrou = threading.Lock()

    def transcribe(
        self,
        audio: np.ndarray,
        language: str = config.STT_LANGUAGE,
    ) -> str:
        """Transcrit un signal audio (float32 mono, [-1, 1]) en texte."""
        if audio.size == 0:
            return ""

        with self._verrou:
            segments, _ = self.model.transcribe(
                audio,
                language=language,
                beam_size=5,
                vad_filter=True,  # filtre les silences internes, évite les hallucinations
            )
            # `segments` est un générateur paresseux : le consommer sous verrou.
            return " ".join(segment.text.strip() for segment in segments).strip()
