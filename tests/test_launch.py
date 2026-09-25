"""Tests pour la comparaison de version de launch.py (logique pure et Git réel
sur un dépôt temporaire) — pas de réseau."""
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import launch  # noqa: E402

A = "a" * 40
B = "b" * 40


def test_est_a_jour_meme_commit_ou_local_en_avance():
    assert launch.est_a_jour(A, A, local_contient_distant=False)
    assert launch.est_a_jour(A, B, local_contient_distant=True)  # travail non poussé
    assert not launch.est_a_jour(A, B, local_contient_distant=False)


def test_commit_local_lit_le_fichier_version_sans_git(tmp_path):
    (tmp_path / ".version").write_text(A + "\n", encoding="utf-8")
    with patch.object(launch, "BASE_DIR", tmp_path), patch.object(
        launch, "COMMIT_LOCAL_PATH", tmp_path / ".version"
    ):
        assert launch.commit_local() == A


def test_commit_local_inconnu_sans_git_ni_fichier(tmp_path):
    with patch.object(launch, "BASE_DIR", tmp_path), patch.object(
        launch, "COMMIT_LOCAL_PATH", tmp_path / ".version"
    ):
        assert launch.commit_local() is None


def test_commit_distant_refuse_une_reponse_qui_n_est_pas_un_sha():
    """La réponse est affichée dans le terminal : une réponse inattendue
    (page HTML, séquences d'échappement) ne doit jamais l'être."""
    class Reponse:
        def __init__(self, texte):
            self.texte = texte

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return self.texte.encode()

    with patch("launch.urllib.request.urlopen", return_value=Reponse(A)):
        assert launch.commit_distant() == A
    with patch("launch.urllib.request.urlopen", return_value=Reponse("\x1b[31mpiege")):
        assert launch.commit_distant() is None


def test_clone_en_avance_est_a_jour(tmp_path, capsys):
    def git(*args):
        return subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
            cwd=tmp_path, capture_output=True, text=True, check=True,
        ).stdout.strip()

    git("init", "-q")
    git("commit", "-q", "--allow-empty", "-m", "un")
    distant = git("rev-parse", "HEAD")
    git("commit", "-q", "--allow-empty", "-m", "deux")  # non poussé

    with patch.object(launch, "BASE_DIR", tmp_path), patch(
        "launch.commit_distant", return_value=distant
    ):
        launch.verifier_version()
        assert "Code à jour" in capsys.readouterr().out

        # Un commit distant inconnu du clone = le clone est en retard.
        with patch("launch.commit_distant", return_value=B):
            launch.verifier_version()
            assert "Nouvelle version" in capsys.readouterr().out
