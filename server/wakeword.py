"""Détection du mot-clé (wake word) via openWakeWord."""
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
        # Contrairement à ce qu'on pourrait attendre, Model(...) ne télécharge
        # pas ses poids tout seul au premier lancement : il faut appeler
        # download_models() explicitement avant, sans quoi le chargement
        # échoue (fichier .onnx manquant). Sans effet si déjà présents
        # (download_models() vérifie avant de retélécharger) — stockés dans
        # l'installation d'openWakeWord elle-même (venv), pas dans models/.
        download_models(model_names=[model_name])

        # inference_framework="onnx" : évite la dépendance à tflite-runtime,
        # dont les wheels sont peu fiables sous Windows/Python récents.
        self.model = Model(wakeword_models=[model_name], inference_framework="onnx")
        self.threshold = threshold
        self.sample_rate = sample_rate
        # openWakeWord attend des blocs de 80 ms (soit 1280 échantillons à 16 kHz)
        self.chunk_size = 1280

    def wait_for_wakeword(self, debug: bool = False) -> None:
        """Bloque le thread courant jusqu'à ce que le mot-clé soit prononcé.

        En mode debug, affiche le score en continu : utile pour calibrer
        WAKE_WORD_THRESHOLD (regarde le score max atteint en disant le mot-clé,
        et le score de fond quand tu ne dis rien)."""
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
