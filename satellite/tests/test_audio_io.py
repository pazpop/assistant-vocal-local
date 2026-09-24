"""Tests pour generer_bip (logique pure) — pas record_until_silence/
play_audio, qui dépendent du matériel audio réel."""
import numpy as np

from audio_io import generer_bip


def test_generer_bip_produit_de_laudio_dans_la_bonne_plage():
    bip = generer_bip(sample_rate=16000, duree=0.15)
    assert bip.dtype == np.float32
    assert bip.size == int(16000 * 0.15)
    assert np.all(np.abs(bip) <= 0.3 + 1e-6)
