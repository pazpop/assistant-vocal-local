"""Tests pour generer_bip et la détection de fin de parole (logique pure) —
pas record_until_silence/play_audio, qui dépendent du matériel audio réel."""
import numpy as np

from audio_io import (
    BLOCS_LISSAGE,
    SEUIL_MAX,
    DetecteurFinParole,
    _niveau,
    generer_bip,
)


def test_generer_bip_produit_de_laudio_dans_la_bonne_plage():
    bip = generer_bip(sample_rate=16000, duree=0.15)
    assert bip.dtype == np.float32
    assert bip.size == int(16000 * 0.15)
    assert np.all(np.abs(bip) <= 0.3 + 1e-6)


def test_niveau_ignore_le_decalage_continu():
    """Un décalage DC constant (défaut de certains codecs micro) ne doit pas
    faire passer un silence pour du son : sinon la fin de parole n'est jamais
    détectée."""
    assert _niveau(np.full(512, 0.5, dtype=np.float32)) < 1e-6

    t = np.linspace(0, 1, 512, endpoint=False)
    sinus = 0.2 * np.sin(2 * np.pi * 8 * t)
    assert abs(_niveau(sinus) - _niveau(sinus + 0.3)) < 1e-6
    assert abs(_niveau(sinus) - 0.2 / np.sqrt(2)) < 0.01


def _detecteur(seuil_min=0.02, blocs_silence=5) -> DetecteurFinParole:
    return DetecteurFinParole(seuil_min=seuil_min, blocs_silence_requis=blocs_silence)


def _nourrir(detecteur, niveaux):
    return [detecteur.traiter(n) for n in niveaux]


def test_piece_calme_se_comporte_comme_un_seuil_fixe():
    d = _detecteur(seuil_min=0.02)
    _nourrir(d, [0.005] * 10)
    assert d.seuil == 0.02  # 2 × 0.005 est sous le minimum configuré

    assert all(_nourrir(d, [0.1] * 5))
    assert d.parole_commencee and not d.fini

    _nourrir(d, [0.005] * 4)
    assert not d.fini
    _nourrir(d, [0.005])
    assert d.fini


def test_bruit_de_fond_constant_eleve_ne_compte_pas_comme_parole():
    """Le cas réel du HAT micro : un niveau de fond constant au-dessus du seuil
    configuré. Avec un seuil fixe, tout était de la parole et l'attente allait
    jusqu'à la durée max ; le bruit seul ne doit jamais démarrer la parole."""
    d = _detecteur(seuil_min=0.02)
    resultats = _nourrir(d, [0.05] * 100)

    assert not any(resultats)
    assert not d.parole_commencee
    assert not d.fini
    assert abs(d.niveau_fond - 0.05) < 1e-9
    assert abs(d.seuil - 0.10) < 1e-9


def test_fin_de_parole_detectee_malgre_un_bruit_de_fond_eleve():
    d = _detecteur(seuil_min=0.02, blocs_silence=5)
    _nourrir(d, [0.05] * 30)  # bruit de fond
    assert all(_nourrir(d, [0.2] * 20))  # parole bien au-dessus du bruit
    assert d.parole_commencee

    _nourrir(d, [0.05] * 4)
    assert not d.fini
    _nourrir(d, [0.05])
    assert d.fini  # la fin est détectée alors que 0.05 > seuil_min (0.02)


def test_le_bruit_de_fond_ne_monte_pas_pendant_la_parole():
    d = _detecteur()
    _nourrir(d, [0.03] * 10)
    _nourrir(d, [0.3] * 50)
    assert abs(d.niveau_fond - 0.03) < 1e-9


def test_le_seuil_est_plafonne():
    """Un début de parole pris pour du bruit de fond ne doit pas relever le
    seuil au-dessus de la parole elle-même."""
    d = _detecteur()
    _nourrir(d, [0.4] * BLOCS_LISSAGE)
    assert d.seuil == SEUIL_MAX


def test_les_premiers_blocs_ne_sont_jamais_classes_comme_parole():
    """Le bruit de fond n'est pas encore mesuré sur les premiers blocs : on
    n'affirme rien plutôt que de prendre du bruit pour de la parole."""
    d = _detecteur()
    resultats = _nourrir(d, [0.5] * BLOCS_LISSAGE)
    assert resultats == [False] * (BLOCS_LISSAGE - 1) + [True]
