"""Tests pour chrono.py : le texte affiché pour montrer où passe le temps —
pas de matériel audio ni de réseau."""
from chrono import formater_etape, resumer_enregistrement


def test_resume_ventile_avant_parole_et_silence():
    texte = resumer_enregistrement(
        duree_s=6.4,
        debut_parole_s=2.1,
        fin_parole_s=5.4,
        coupe_par_duree_max=False,
        duree_max_s=15,
    )

    assert "Enregistrement : 6.4 s" in texte
    assert "2.1 s avant de parler" in texte
    assert "3.3 s de parole" in texte
    assert "1.0 s de silence attendu" in texte
    assert "⚠️" not in texte


def test_resume_signale_un_arret_par_la_duree_max():
    """Un enregistrement coupé par la durée max = fin de parole jamais
    détectée (typiquement du bruit de fond) : c'est la cause probable de
    plusieurs secondes d'attente avant l'envoi, il faut le dire clairement."""
    texte = resumer_enregistrement(
        duree_s=15.0,
        debut_parole_s=0.1,
        fin_parole_s=15.0,
        coupe_par_duree_max=True,
        duree_max_s=15,
    )

    assert "arrêté par la durée max (15 s)" in texte
    assert "--debug-audio" in texte


def test_resume_ne_donne_jamais_de_duree_negative():
    texte = resumer_enregistrement(
        duree_s=1.0,
        debut_parole_s=0.0,
        fin_parole_s=1.05,  # arrondi de bloc au-delà de la durée totale
        coupe_par_duree_max=False,
        duree_max_s=15,
    )

    assert "0.0 s de silence attendu" in texte


def test_etape_wav_cree():
    ligne = formater_etape("wav_cree", duree_audio=5.2, octets=166_400, duree_encodage=0.004)
    assert ligne == "📦 WAV créé : 5.2 s d'audio, 162 Ko (encodage 4 ms)"


def test_etape_envoi():
    assert formater_etape("envoi") == "📤 Envoi au serveur..."


def test_etape_transcription_finie():
    ligne = formater_etape("transcription_finie", depuis_envoi=1.354)
    assert "transcription terminée" in ligne
    assert "+1.35 s" in ligne


def test_etape_premiere_phrase_separe_transcription_et_llm():
    ligne = formater_etape("premiere_phrase", depuis_envoi=2.05, depuis_transcription=0.7)
    assert "+2.05 s après l'envoi" in ligne
    assert "0.70 s de LLM + synthèse" in ligne


def test_etape_inconnue_n_affiche_rien():
    assert formater_etape("etape-qui-n-existe-pas") is None
