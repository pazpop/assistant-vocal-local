"""Tests pour la logique pure de client_api.py (conversion WAV, réassemblage
des trames de réponse) — pas de vrai appel réseau, pas de matériel audio."""
import struct

import numpy as np
import pytest
import requests

from client_api import _audio_vers_wav, _extraire_trames, _wav_vers_audio


def _trame(contenu: bytes) -> bytes:
    """Même format que server/satellite_api.py (_trame) : taille 4 octets
    big-endian + contenu."""
    return struct.pack(">I", len(contenu)) + contenu


def test_extraire_trames_recompose_les_phrases_meme_decoupees_n_importe_ou():
    """Le réseau découpe le flux à sa guise (au milieu d'une taille, d'un
    WAV...) : on doit retrouver exactement les mêmes trames."""
    flux = _trame(b"premiere") + _trame(b"deuxieme phrase") + _trame(b"3")
    for pas in (1, 2, 3, 5, 7, len(flux)):
        morceaux = [flux[i : i + pas] for i in range(0, len(flux), pas)]
        assert list(_extraire_trames(morceaux)) == [b"premiere", b"deuxieme phrase", b"3"]


def test_extraire_trames_produit_une_phrase_des_qu_elle_est_complete():
    """La 1re phrase doit sortir sans attendre la 2e : sinon on n'a rien
    gagné par rapport à une réponse envoyée d'un bloc."""
    lu = []

    def morceaux():
        for m in [_trame(b"un"), _trame(b"deux")]:
            lu.append(m)
            yield m

    trames = _extraire_trames(morceaux())
    assert next(trames) == b"un"
    assert len(lu) == 1


def test_extraire_trames_leve_si_le_flux_est_coupe_en_pleine_phrase():
    flux = _trame(b"complete") + _trame(b"tronquee")[:-3]
    with pytest.raises(requests.exceptions.ChunkedEncodingError):
        list(_extraire_trames([flux]))


def test_extraire_trames_flux_vide():
    assert list(_extraire_trames([])) == []


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
