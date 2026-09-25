"""Tests pour satellite_api.py : conversion WAV, trames de réponse en flux,
clé API, et les endpoints via TestClient (sans vrai serveur uvicorn, micro
ni Piper : STT, TTS et LLM sont factices).
"""
import io
import struct
import wave
from unittest.mock import patch

import numpy as np
import pytest
from fastapi.testclient import TestClient

import satellite_api
from satellite_api import (
    BoiteNotifications,
    WavInvalide,
    _audio_vers_wav,
    _cle_api_valide,
    _trame,
    _trames_reponse,
    _wav_vers_audio,
    creer_app,
)

CLE = "cle-de-test-0123456789"


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
        with wave.open(io.BytesIO(trame[4:])) as f:
            assert f.getnframes() == 10


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


def test_cle_api_non_ascii_refusee_sans_planter():
    """compare_digest lève TypeError sur une str non ASCII : l'en-tête
    X-API-Key: é ne doit pas faire un 500."""
    with patch("satellite_api.config.SATELLITE_API_KEY", "secret123"):
        assert not _cle_api_valide("é")


def _wav(canaux=1, largeur=2, frequence=16000, nframes=1600):
    tampon = io.BytesIO()
    with wave.open(tampon, "wb") as f:
        f.setnchannels(canaux)
        f.setsampwidth(largeur)
        f.setframerate(frequence)
        f.writeframes(b"\x00" * nframes * canaux * largeur)
    return tampon.getvalue()


def test_wav_vers_audio_accepte_le_format_attendu():
    assert _wav_vers_audio(_wav()).size == 1600


@pytest.mark.parametrize(
    "donnees",
    [
        _wav(canaux=2),
        _wav(frequence=48000),
        _wav(largeur=1),
        _wav(nframes=16000 * 61),
        b"ceci n'est pas un wav",
    ],
    ids=["stereo", "48kHz", "8bits", "trop-long", "pas-un-wav"],
)
def test_wav_vers_audio_refuse_un_format_inattendu(donnees):
    with pytest.raises(WavInvalide):
        _wav_vers_audio(donnees)


class FauxSTT:
    def __init__(self, texte="quelle heure est-il"):
        self.texte = texte

    def transcribe(self, signal):
        return self.texte


@pytest.fixture
def client():
    boite = BoiteNotifications()
    zones = []

    def repondre_flux(question, zone):
        zones.append(zone)
        return ["Il est midi."]

    with patch("satellite_api.config.SATELLITE_API_KEY", CLE):
        app = creer_app(FauxSTT(), FauxTTS(), repondre_flux, boite)
        c = TestClient(app)
        c.boite = boite
        c.zones = zones
        yield c


def test_assistant_repond_en_trames_avec_la_zone(client):
    reponse = client.post(
        "/assistant", content=_wav(), headers={"X-API-Key": CLE, "X-Zone": "cuisine"}
    )

    assert reponse.status_code == 200
    assert struct.unpack(">I", reponse.content[:4])[0] == len(reponse.content) - 4
    assert client.zones == ["cuisine"]


def test_assistant_zone_par_defaut(client):
    client.post("/assistant", content=_wav(), headers={"X-API-Key": CLE})
    assert client.zones == [satellite_api.ZONE_PAR_DEFAUT]


def test_assistant_refuse_sans_cle_et_avec_cle_non_ascii(client):
    assert client.post("/assistant", content=_wav()).status_code == 401
    mauvaise = client.post(
        "/assistant", content=_wav(), headers={"X-API-Key": "é".encode("latin-1")}
    )
    assert mauvaise.status_code == 401


def test_assistant_refuse_un_corps_trop_gros_sans_le_lire(client):
    enorme = b"\x00" * (satellite_api.TAILLE_MAX_QUESTION + 1)
    reponse = client.post("/assistant", content=enorme, headers={"X-API-Key": CLE})
    assert reponse.status_code == 413


def test_assistant_refuse_un_wav_invalide(client):
    reponse = client.post("/assistant", content=b"pas un wav", headers={"X-API-Key": CLE})
    assert reponse.status_code == 400


def test_notifications_livrees_une_seule_fois_a_la_bonne_zone(client):
    client.boite.deposer("cuisine", np.full(10, 0.5, dtype=np.float32), 22050)
    entetes = {"X-API-Key": CLE, "X-Zone": "cuisine"}

    assert client.get("/notifications", headers={"X-API-Key": CLE, "X-Zone": "salon"}).content == b""
    premiere = client.get("/notifications", headers=entetes)
    assert struct.unpack(">I", premiere.content[:4])[0] == len(premiere.content) - 4
    assert client.get("/notifications", headers=entetes).content == b""


def test_notifications_refusees_sans_cle(client):
    assert client.get("/notifications").status_code == 401


def test_boite_notifications_abandonne_les_plus_anciennes():
    boite = BoiteNotifications()
    for _ in range(satellite_api.NOTIFICATIONS_MAX_PAR_ZONE + 5):
        boite.deposer("z", np.zeros(4, dtype=np.float32), 16000)

    nb_trames = len(boite.retirer("z")) // len(_trame(_audio_vers_wav(np.zeros(4, dtype=np.float32), 16000)))
    assert nb_trames == satellite_api.NOTIFICATIONS_MAX_PAR_ZONE
