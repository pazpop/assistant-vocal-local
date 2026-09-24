"""Détection du mot-clé (wake word) via openWakeWord.

Identique à server/wakeword.py, dupliqué ici volontairement : le satellite
n'importe rien de server/ (qui embarque STT/LLM/TTS, inutiles ici), pour
rester une installation autonome sur le Pi.
"""
import sounddevice as sd
from openwakeword.model import Model
from openwakeword.utils import download_models

import config


class WakeWordDetector:
    def __init__(
        self,
        model_name: str = config.WAKE_WORD_MODEL,
        threshold: float = config.WAKE_WORD_THRESHOLD,
        sample_rate: int = config.SAMPLE_RATE,
    ):
        # Model(...) ne télécharge pas ses poids tout seul : download_models()
        # est requis avant, sans quoi le chargement échoue. Sans effet si
        # déjà présents.
        download_models(model_names=[model_name])

        # inference_framework="onnx" : cohérent avec server/wakeword.py.
        self.model = Model(wakeword_models=[model_name], inference_framework="onnx")
        self.threshold = threshold
        self.sample_rate = sample_rate
        # openWakeWord attend des blocs de 80 ms (soit 1280 échantillons à 16 kHz)
        self.chunk_size = 1280

    def wait_for_wakeword(self, debug: bool = False) -> None:
        """Bloque le thread courant jusqu'à ce que le mot-clé soit prononcé.

        En mode debug, affiche le score en continu : utile pour calibrer
        wake_word.threshold (regarde le score max atteint en disant le
        mot-clé, et le score de fond quand tu ne dis rien)."""
        self.model.reset()
        best_score = 0.0

        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=self.chunk_size,
            device=config.AUDIO_INPUT_DEVICE,
        ) as stream:
            while True:
                audio_block, _ = stream.read(self.chunk_size)
                audio_block = audio_block.flatten()

                predictions = self.model.predict(audio_block)
                score = max(predictions.values())

                if debug:
                    best_score = max(best_score, score)
                    print(
                        f"\r[wakeword] score={score:.3f}  max_vu={best_score:.3f}  "
                        f"seuil={self.threshold:.2f}   ",
                        end="",
                        flush=True,
                    )

                if score > self.threshold:
                    if debug:
                        print()
                    return
