"""Tests pour la logique pure de satellite_api.py : conversion WAV, trames de
réponse en flux et validation de clé API — pas le vrai serveur HTTP
(uvicorn), le micro ni Piper.
"""
import struct
from unittest.mock import patch

import numpy as np

from satellite_api import (
    _audio_vers_wav,
    _cle_api_valide,
    _trame,
    _trames_reponse,
    _wav_vers_audio,
)


class FauxTTS:
    """Remplace Piper : un signal de 10 échantillons par phrase, et garde
    trace des phrases reçues pour vérifier ce qui a été synthétisé."""

    sample_rate = 22050

    def __init__(self):
        self.appels = []

    def synthesize(self, texte):
        self.appels.append(texte)
        return np.full(10, 0.5, dtype=np.float32)


def test_wav_aller_retour_preserve_le_signal():
    """L'encodage/décodage WAV (satellite <-> serveur) ne doit pas déformer
    le signal au-delà de la perte attendue de la quantification 16 bits."""
    original = np.array([0.0, 0.5, -0.5, 0.999, -1.0], dtype=np.float32)
    wav = _audio_vers_wav(original, sample_rate=16000)
    reconstruit = _wav_vers_audio(wav)

    assert np.allclose(reconstruit, original, atol=1e-4)


def test_trame_prefixe_la_taille_du_wav():
    wav = b"RIFF-un-faux-wav"
    trame = _trame(wav)

    assert struct.unpack(">I", trame[:4])[0] == len(wav)
    assert trame[4:] == wav


def test_trames_reponse_produit_une_trame_decodable_par_phrase():
    tts = FauxTTS()
    trames = list(_trames_reponse(tts, ["Bonjour. ", "Ça va ?"]))

    assert tts.appels == ["Bonjour.", "Ça va ?"]
    assert len(trames) == 2
    for trame in trames:
        assert struct.unpack(">I", trame[:4])[0] == len(trame) - 4
        assert _wav_vers_audio(trame[4:]).size == 10


def test_trames_reponse_synthetise_au_fil_de_l_eau():
    """La 1re trame doit sortir avant que le flux du LLM soit épuisé : c'est
    tout l'intérêt du streaming, sinon on retombe sur l'attente complète."""
    tts = FauxTTS()
    lu = []

    def flux():
        for fragment in ["Un. ", "Deux."]:
            lu.append(fragment)
            yield fragment

    trames = _trames_reponse(tts, flux())
    next(trames)

    assert lu == ["Un. "]
    assert tts.appels == ["Un."]


def test_trames_reponse_ignore_une_synthese_vide():
    class TTSMuet(FauxTTS):
        def synthesize(self, texte):
            return np.array([], dtype=np.float32)

    assert list(_trames_reponse(TTSMuet(), ["Bonjour."])) == []


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
