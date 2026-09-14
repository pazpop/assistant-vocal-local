"""Tests pour timer.py : validation des durées et dispatch (démarrer, lister,
annuler), sans vraiment attendre l'expiration d'un minuteur (le callback est
appelé directement)."""
from unittest.mock import MagicMock, patch

from timer import TimerManager, _formater_duree, demande_minuteur, generer_sonnerie


def test_generer_sonnerie_produit_de_l_audio():
    son = generer_sonnerie(16000)
    assert son.size > 0
    assert son.dtype.name == "float32"


def test_demarrer_minuteur_valide():
    with patch("timer.threading.Timer") as mock_timer:
        gestionnaire = TimerManager(on_expire=lambda label: None)
        resultat = gestionnaire.executer_outil(
            "demarrer_minuteur", {"secondes": 30, "label": "pour les pâtes"}
        )

        mock_timer.assert_called_once()
        args, _ = mock_timer.call_args
        delai, _callback = args
        assert delai == 30
        assert "30 secondes" in resultat
        assert "pour les pâtes" in resultat

        mock_timer.return_value.start.assert_called_once()


def test_minuteur_declenche_on_expire_et_se_retire_du_suivi():
    """Vérifie que l'expiration appelle bien on_expire avec le label, et que
    le minuteur disparaît de la liste une fois sonné — sans attendre pour de
    vrai (le callback donné à threading.Timer est invoqué manuellement)."""
    on_expire = MagicMock()
    gestionnaire = TimerManager(on_expire=on_expire)

    with patch("timer.threading.Timer") as mock_timer:
        gestionnaire.executer_outil("demarrer_minuteur", {"secondes": 5, "label": "test"})
        _, callback_expiration = mock_timer.call_args[0]

    assert "1 minuteur" in gestionnaire.lister()
    callback_expiration()
    on_expire.assert_called_once_with("test")
    assert gestionnaire.lister() == "Aucun minuteur en cours."


def test_duree_invalide():
    gestionnaire = TimerManager(on_expire=lambda label: None)
    resultat = gestionnaire.executer_outil("demarrer_minuteur", {"secondes": -5})
    assert "invalide" in resultat.lower()

    resultat = gestionnaire.executer_outil("demarrer_minuteur", {"secondes": 999999})
    assert "invalide" in resultat.lower()


def test_argument_manquant():
    gestionnaire = TimerManager(on_expire=lambda label: None)
    resultat = gestionnaire.executer_outil("demarrer_minuteur", {})
    assert "argument manquant" in resultat.lower()


def test_outil_inconnu():
    gestionnaire = TimerManager(on_expire=lambda label: None)
    resultat = gestionnaire.executer_outil("faire_le_cafe", {})
    assert "inconnu" in resultat.lower()


def test_formater_duree():
    assert _formater_duree(30) == "30 secondes"
    assert _formater_duree(1) == "1 seconde"
    assert _formater_duree(60) == "1 minute"
    assert _formater_duree(120) == "2 minutes"
    assert _formater_duree(150) == "2 minutes 30 secondes"
    assert _formater_duree(61) == "1 minute 1 seconde"


def test_demarrer_minuteur_long_formate_en_minutes():
    with patch("timer.threading.Timer"):
        gestionnaire = TimerManager(on_expire=lambda label: None)
        resultat = gestionnaire.executer_outil("demarrer_minuteur", {"secondes": 300})
    assert "5 minutes" in resultat
    assert "300 secondes" not in resultat


def test_demande_minuteur_detecte_les_phrases_declencheuses():
    assert demande_minuteur("Mets un minuteur de 5 minutes")
    assert demande_minuteur("Démarre un chronomètre de 30 secondes")
    assert demande_minuteur("Lance un compte à rebours de 2 minutes")
    assert demande_minuteur("MINUTEUR de 10 secondes pour les pâtes")


def test_demande_minuteur_ignore_les_autres_questions():
    assert not demande_minuteur("Quel temps fait-il ?")
    assert not demande_minuteur("Quelle heure est-il ?")
    assert not demande_minuteur("Allume la lumière du salon")


def test_lister_minuteurs_vide():
    gestionnaire = TimerManager(on_expire=lambda label: None)
    assert gestionnaire.executer_outil("lister_minuteurs", {}) == "Aucun minuteur en cours."


def test_lister_plusieurs_minuteurs_numerotes_dans_l_ordre_de_creation():
    with patch("timer.threading.Timer"):
        gestionnaire = TimerManager(on_expire=lambda label: None)
        gestionnaire.demarrer(120, "")
        gestionnaire.demarrer(300, "pour les pâtes")

    resultat = gestionnaire.executer_outil("lister_minuteurs", {})
    assert "2 minuteurs" in resultat
    assert "minuteur 1" in resultat
    assert "minuteur 2 pour les pâtes" in resultat


def test_lister_un_minuteur_precis_donne_le_temps_restant():
    with patch("timer.threading.Timer"):
        gestionnaire = TimerManager(on_expire=lambda label: None)
        gestionnaire.demarrer(120, "")

    resultat = gestionnaire.executer_outil("lister_minuteurs", {"numero": 1})
    assert "minuteur 1" in resultat
    assert "2 minutes" in resultat


def test_lister_minuteur_introuvable():
    gestionnaire = TimerManager(on_expire=lambda label: None)
    resultat = gestionnaire.executer_outil("lister_minuteurs", {"numero": 5})
    assert "n'ai pas trouvé" in resultat.lower()


def test_les_numeros_ne_sont_jamais_reattribues():
    """Si le minuteur 1 sonne avant qu'on en démarre un 3ème, le nouveau
    doit être "minuteur 3", jamais "minuteur 1" à la place — pour ne jamais
    désigner le mauvais minuteur par erreur."""
    with patch("timer.threading.Timer") as mock_timer:
        gestionnaire = TimerManager(on_expire=lambda label: None)
        gestionnaire.demarrer(60, "")  # numéro 1
        gestionnaire.demarrer(120, "")  # numéro 2

        # Le 1er sonne (son callback est le premier appel enregistré).
        callback_1 = mock_timer.call_args_list[0][0][1]
        callback_1()

        gestionnaire.demarrer(180, "")  # doit devenir le numéro 3, pas 1

    resultat = gestionnaire.executer_outil("lister_minuteurs", {})
    assert "minuteur 2" in resultat
    assert "minuteur 3" in resultat
    assert "minuteur 1" not in resultat


def test_annuler_un_minuteur_precis():
    with patch("timer.threading.Timer") as mock_timer:
        gestionnaire = TimerManager(on_expire=lambda label: None)
        gestionnaire.demarrer(120, "pour les pâtes")

        resultat = gestionnaire.executer_outil("annuler_minuteur", {"cible": "1"})

        mock_timer.return_value.cancel.assert_called_once()
    assert "minuteur 1" in resultat
    assert gestionnaire.lister() == "Aucun minuteur en cours."


def test_annuler_tous_les_minuteurs():
    with patch("timer.threading.Timer") as mock_timer:
        gestionnaire = TimerManager(on_expire=lambda label: None)
        gestionnaire.demarrer(60, "")
        gestionnaire.demarrer(120, "")

        resultat = gestionnaire.executer_outil("annuler_minuteur", {"cible": "tous"})

        assert mock_timer.return_value.cancel.call_count == 2
    assert "2 minuteur" in resultat
    assert gestionnaire.lister() == "Aucun minuteur en cours."


def test_annuler_minuteur_introuvable():
    gestionnaire = TimerManager(on_expire=lambda label: None)
    resultat = gestionnaire.executer_outil("annuler_minuteur", {"cible": "1"})
    assert "n'ai pas trouvé" in resultat.lower()


def test_annuler_sans_minuteur_actif():
    gestionnaire = TimerManager(on_expire=lambda label: None)
    resultat = gestionnaire.executer_outil("annuler_minuteur", {"cible": "tous"})
    assert "aucun minuteur" in resultat.lower()
