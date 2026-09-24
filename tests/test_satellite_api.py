"""Tests pour la logique pure de satellite_api.py : conversion WAV et
validation de clé API — pas le vrai serveur HTTP (uvicorn), le micro ni Piper.
"""
from unittest.mock import patch

import numpy as np

from satellite_api import _audio_vers_wav, _cle_api_valide, _wav_vers_audio


def test_wav_aller_retour_preserve_le_signal():
    """L'encodage/décodage WAV (satellite <-> serveur) ne doit pas déformer
    le signal au-delà de la perte attendue de la quantification 16 bits."""
    original = np.array([0.0, 0.5, -0.5, 0.999, -1.0], dtype=np.float32)
    wav = _audio_vers_wav(original, sample_rate=16000)
    reconstruit = _wav_vers_audio(wav)

    assert np.allclose(reconstruit, original, atol=1e-4)


def test_cle_api_valide_refuse_une_cle_vide_dans_la_config():
    """Une clé vide dans config.yml doit désactiver l'accès, pas l'ouvrir à
    n'importe quelle requête sans en-tête X-API-Key."""
    with patch("satellite_api.config.SATELLITE_API_KEY", ""):
        assert not _cle_api_valide("")
        assert not _cle_api_valide("nimporte-quoi")


def test_cle_api_valide_compare_a_la_config():
    with patch("satellite_api.config.SATELLITE_API_KEY", "secret123"):
        assert _cle_api_valide("secret123")
        assert not _cle_api_valide("mauvaise-cle")
        assert not _cle_api_valide("")
