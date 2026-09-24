"""Tests pour la logique pure de client_api.py (conversion WAV) — pas de
vrai appel réseau, pas de matériel audio."""
import numpy as np

from client_api import _audio_vers_wav, _wav_vers_audio


def test_wav_aller_retour_preserve_le_signal_et_la_frequence():
    original = np.array([0.0, 0.5, -0.5, 0.999, -1.0], dtype=np.float32)
    wav = _audio_vers_wav(original, sample_rate=16000)
    reconstruit, sample_rate = _wav_vers_audio(wav)

    assert sample_rate == 16000
    assert np.allclose(reconstruit, original, atol=1e-4)


def test_wav_vers_audio_preserve_une_frequence_differente():
    """La réponse du serveur (voix Piper) n'est pas à 16 kHz — s'assurer
    qu'on ne la force pas à tort à la fréquence d'enregistrement du micro."""
    wav = _audio_vers_wav(np.zeros(100, dtype=np.float32), sample_rate=44100)
    _audio, sample_rate = _wav_vers_audio(wav)
    assert sample_rate == 44100
