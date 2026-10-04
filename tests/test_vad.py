"""Tests pour vad.py : charge le vrai modèle ONNX (léger, CPU, déjà présent
via faster-whisper) et vérifie son comportement sur des signaux synthétiques."""
import numpy as np
import pytest

from vad import VoiceActivityDetector


@pytest.fixture(scope="module")
def vad() -> VoiceActivityDetector:
    return VoiceActivityDetector()


def test_silence_donne_une_probabilite_faible(vad):
    vad.reset()
    silence = np.zeros(vad.NUM_SAMPLES, dtype=np.float32)
    probas = [vad.probabilite_parole(silence) for _ in range(10)]
    assert all(0.0 <= p <= 1.0 for p in probas)
    assert max(probas) < 0.1


def test_bruit_blanc_ne_declenche_pas_a_tort(vad):
    """Un simple seuil sur le volume confondrait du bruit fort avec de la
    parole ; un vrai VAD ne devrait pas s'y laisser prendre."""
    vad.reset()
    rng = np.random.default_rng(0)
    bruit = (rng.standard_normal(vad.NUM_SAMPLES) * 0.3).astype(np.float32)
    probas = [vad.probabilite_parole(bruit) for _ in range(10)]
    assert max(probas) < 0.5


def test_reset_efface_l_etat_interne(vad):
    """Après reset(), l'état (mémoire récurrente + contexte) doit repartir
    de zéro, indépendamment de ce qui a été traité juste avant."""
    vad.reset()
    bruit_fort = np.ones(vad.NUM_SAMPLES, dtype=np.float32) * 0.9
    for _ in range(5):
        vad.probabilite_parole(bruit_fort)

    vad.reset()
    assert np.array_equal(vad._h, np.zeros((1, 1, 128), dtype=np.float32))
    assert np.array_equal(vad._c, np.zeros((1, 1, 128), dtype=np.float32))
    assert np.array_equal(vad._contexte, np.zeros(vad.CONTEXT_SAMPLES, dtype=np.float32))


def test_rejette_un_bloc_de_taille_incorrecte(vad):
    vad.reset()
    with pytest.raises(ValueError):
        vad.probabilite_parole(np.zeros(100, dtype=np.float32))
