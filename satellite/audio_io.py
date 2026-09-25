"""Capture micro et lecture haut-parleur pour le client satellite.

Détection de fin de parole par seuil de volume, pas par VAD Silero comme le
serveur (server/vad.py) : ce modèle est normalement récupéré depuis
l'installation de faster-whisper (get_assets_path()), qui n'a aucune raison
d'être installée sur le satellite (STT reste géré côté serveur, voir
server/satellite_api.py). Le paquet silero-vad sur PyPI dépend de PyTorch
même pour son mode ONNX — bien trop lourd sur un Raspberry Pi juste pour
détecter un silence.

Le seuil n'est pas fixe : il s'adapte au bruit de fond du micro mesuré à
chaque enregistrement (voir DetecteurFinParole). Un seuil fixe trop bas pour
un HAT micro au bruit de fond élevé prend toute la durée pour de la parole :
la fin n'est jamais détectée et l'attente va jusqu'à max_record_seconds.
Moins robuste que le VAD du serveur face à un bruit de fond très variable
(télé, radio) — limite connue, pas un oubli (voir ARCHITECTURE.md).
"""
import queue
import threading
from collections import deque
from dataclasses import dataclass

import numpy as np
import sounddevice as sd

import config

BLOCK_SIZE = 512  # ~32 ms à 16 kHz, cohérent avec la taille de bloc VAD du serveur

# Seuil de parole = FACTEUR_BRUIT × bruit de fond mesuré (sans jamais descendre
# sous audio.silence_threshold), plafonné à SEUIL_MAX : sans plafond, un début
# de parole pris à tort pour du bruit de fond relèverait le seuil au-dessus de
# la parole elle-même et rien ne serait plus détecté.
FACTEUR_BRUIT = 2.0
SEUIL_MAX = 0.12
BLOCS_LISSAGE = 3  # ~100 ms : lisse le niveau avant d'en tirer le bruit de fond


@dataclass
class Enregistrement:
    """Résultat de record_until_silence : l'audio et les instants clés, pour
    afficher où passe le temps avant l'envoi au serveur (voir chrono.py)."""

    audio: np.ndarray  # mono float32 [-1, 1], vide si aucune parole n'a démarré
    duree_s: float  # durée totale enregistrée
    debut_parole_s: float  # secondes écoulées avant le premier bloc de parole
    fin_parole_s: float  # instant de fin du dernier bloc de parole
    coupe_par_duree_max: bool  # max_record_seconds atteint sans fin de parole détectée
    niveau_fond: float  # bruit de fond mesuré (0.0 si trop court pour être mesuré)
    seuil: float  # seuil de parole effectivement utilisé à la fin


def _niveau(bloc: np.ndarray) -> float:
    """Niveau (RMS) d'un bloc SANS sa composante continue : certains codecs
    micro ont un décalage DC constant qui, compté dans le RMS, ferait passer
    un silence parfait pour un signal audible."""
    return float(np.std(bloc))


class DetecteurFinParole:
    """Décide, bloc par bloc, si l'utilisateur parle et quand il a fini.

    Le seuil de parole est le plus grand de `seuil_min` (config) et de
    FACTEUR_BRUIT × le bruit de fond, plafonné à SEUIL_MAX. Le bruit de fond
    est le niveau lissé le plus bas rencontré depuis le début de
    l'enregistrement : la parole, plus forte, ne le fait jamais monter.

    Les premiers blocs (BLOCS_LISSAGE) servent à mesurer ce bruit et ne sont
    jamais classés comme parole : sans ça, du bruit de fond serait pris pour
    de la parole tant que le seuil n'est pas calibré. L'audio de ces blocs est
    quand même enregistré (~100 ms), rien n'est perdu pour le serveur."""

    def __init__(self, seuil_min: float, blocs_silence_requis: int):
        self.seuil_min = seuil_min
        self.blocs_silence_requis = blocs_silence_requis
        self.niveau_fond: float | None = None
        self.parole_commencee = False
        self._blocs_silence = 0
        self._recents: deque[float] = deque(maxlen=BLOCS_LISSAGE)

    @property
    def seuil(self) -> float:
        fond = self.niveau_fond if self.niveau_fond is not None else 0.0
        return min(SEUIL_MAX, max(self.seuil_min, FACTEUR_BRUIT * fond))

    @property
    def fini(self) -> bool:
        return self.parole_commencee and self._blocs_silence >= self.blocs_silence_requis

    @property
    def blocs_silence(self) -> int:
        return self._blocs_silence

    def traiter(self, niveau: float) -> bool:
        """Prend en compte le niveau d'un bloc, retourne True si c'est de la parole."""
        self._recents.append(niveau)
        if len(self._recents) < BLOCS_LISSAGE:
            return False

        lisse = sum(self._recents) / BLOCS_LISSAGE
        self.niveau_fond = lisse if self.niveau_fond is None else min(self.niveau_fond, lisse)

        if niveau > self.seuil:
            self.parole_commencee = True
            self._blocs_silence = 0
            return True

        if self.parole_commencee:
            self._blocs_silence += 1
        return False


def record_until_silence(debug: bool = False) -> Enregistrement:
    """Enregistre le micro jusqu'à un silence prolongé (ou max_record_seconds).

    `.audio` est un tableau numpy mono float32 normalisé dans [-1, 1] — même
    format que server/audio_io.py — ou un tableau vide si aucune parole n'a
    démarré (permet à l'appelant de distinguer "rien dit" de "a parlé")."""
    sample_rate = config.SAMPLE_RATE
    duree_bloc = BLOCK_SIZE / sample_rate
    silence_blocks_needed = max(1, round(config.SILENCE_DURATION / duree_bloc))
    max_blocks = max(1, round(config.MAX_RECORD_SECONDS / duree_bloc))

    detecteur = DetecteurFinParole(config.SILENCE_THRESHOLD, silence_blocks_needed)
    audio_chunks = []
    premier_bloc_parole = 0
    dernier_bloc_parole = 0
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

            niveau = _niveau(block.flatten())
            deja_parle = detecteur.parole_commencee
            est_parole = detecteur.traiter(niveau)

            if est_parole:
                if not deja_parle:
                    premier_bloc_parole = indice_bloc
                dernier_bloc_parole = indice_bloc

            if debug:
                etat = "parole" if est_parole else "silence"
                print(
                    f"\r[audio] niveau={niveau:.3f}  fond={detecteur.niveau_fond or 0.0:.3f}  "
                    f"seuil={detecteur.seuil:.3f}  "
                    f"({etat}, {detecteur.blocs_silence}/{silence_blocks_needed})   ",
                    end="",
                    flush=True,
                )

            if detecteur.fini:
                break

    if debug:
        print()

    audio = (
        np.concatenate(audio_chunks, axis=0).flatten()
        if audio_chunks and detecteur.parole_commencee
        else np.array([], dtype=np.float32)
    )
    return Enregistrement(
        audio=audio,
        duree_s=len(audio_chunks) * duree_bloc,
        debut_parole_s=premier_bloc_parole * duree_bloc,
        fin_parole_s=(dernier_bloc_parole + 1) * duree_bloc,
        coupe_par_duree_max=not detecteur.fini,
        niveau_fond=detecteur.niveau_fond or 0.0,
        seuil=detecteur.seuil,
    )


_verrou_lecture = threading.Lock()  # réponse et notification (thread de fond) ne se chevauchent pas


def play_audio(audio: np.ndarray, sample_rate: int) -> None:
    """Joue un signal audio sur le haut-parleur configuré (bloquant)."""
    if audio.size == 0:
        return
    with _verrou_lecture:
        sd.play(audio, samplerate=sample_rate, device=config.AUDIO_OUTPUT_DEVICE)
        sd.wait()


def generer_bip(sample_rate: int, frequence: float = 880.0, duree: float = 0.15) -> np.ndarray:
    """Court bip sinusoïdal joué dès le mot-clé détecté, pour confirmer que
    le satellite écoute — pas de TTS local pour dire une phrase comme le fait
    le serveur (voir main.py), donc un simple signal sonore à la place."""
    t = np.linspace(0, duree, int(sample_rate * duree), endpoint=False)
    return (0.3 * np.sin(2 * np.pi * frequence * t)).astype(np.float32)
