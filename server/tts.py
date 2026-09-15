"""Synthèse vocale (Text-to-Speech) avec Piper (OHF-Voice/piper1-gpl, GPL-3.0).

Piper tourne bien sur CPU (utile aussi pour tes futurs satellites Raspberry
Pi), n'embarque aucun filigrane ni mécanisme de traçabilité, et streame
l'audio par petits blocs — pratique pour le pipeline LLM->TTS en streaming.
"""
import threading

import numpy as np
from piper import PiperVoice
from piper.config import SynthesisConfig

import config


class TextToSpeech:
    def __init__(
        self,
        model_path: str = config.TTS_VOICE_MODEL,
        use_cuda: bool = config.TTS_USE_CUDA,
        speaker_id: int | None = config.TTS_SPEAKER_ID,
    ):
        self.voice = PiperVoice.load(model_path, use_cuda=use_cuda)
        # Ignoré par les voix mono-locuteur (siwis, tom...) ; nécessaire pour
        # choisir la voix désirée parmi celles d'un modèle multi-locuteurs
        # (ex: mls, qui en propose 125).
        self._syn_config = SynthesisConfig(speaker_id=speaker_id) if speaker_id is not None else None
        # Valeur par défaut ; mise à jour dès le premier bloc audio reçu
        # (fiable quelle que soit la version de piper-tts installée).
        self.sample_rate = 22050
        # Un seul objet TextToSpeech est partagé entre le thread principal
        # (réponses en streaming) et les threads de fond (minuteurs, alertes
        # météo proactives, voir main.py) : sans ce verrou, deux synthèses
        # simultanées sur le même self.voice pourraient se chevaucher.
        self._verrou_synthese = threading.Lock()

    def synthesize(self, text: str) -> np.ndarray:
        """Génère l'audio (float32 mono, [-1, 1]) correspondant au texte."""
        if not text.strip():
            return np.array([], dtype=np.float32)

        with self._verrou_synthese:
            morceaux = []
            for chunk in self.voice.synthesize(text, syn_config=self._syn_config):
                self.sample_rate = chunk.sample_rate
                morceaux.append(np.frombuffer(chunk.audio_int16_bytes, dtype=np.int16))

        if not morceaux:
            return np.array([], dtype=np.float32)

        audio_int16 = np.concatenate(morceaux)
        return audio_int16.astype(np.float32) / 32768.0
