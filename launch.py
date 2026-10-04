"""Lance la stack Jarvis (+ Open WebUI en option) en un seul script.
Chaque composant tourne dans son propre venv, comme processus séparé.

Ne démarre PAS Ollama : c'est un service Windows qui tourne déjà en
arrière-plan une fois installé — voir README.md. Ce script vérifie
seulement qu'il répond, avec un message clair sinon. Windows uniquement.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Emojis dans une console non UTF-8 (ex: cp1252) : sans ça, le premier print() plante.
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent
SERVER_DIR = BASE_DIR / "server"
OPENWEBUI_DIR = BASE_DIR / "openwebui"
SERVER_PYTHON = BASE_DIR / ".venv" / "Scripts" / "python.exe"
OPENWEBUI_EXE = OPENWEBUI_DIR / ".venv-openwebui" / "Scripts" / "open-webui.exe"

OLLAMA_URL = "http://localhost:11434/api/version"
COMMIT_DISTANT_URL = "https://api.github.com/repos/pazpop/assistant-vocal-local/commits/main"
# Écrit par install.ps1 pour une installation par .zip (sans Git) ; ignoré si le dossier est un clone.
COMMIT_LOCAL_PATH = BASE_DIR / ".version"

# Open WebUI dans sa propre console : ses logs verbeux ne se mêlent pas à ceux de Jarvis.
CREATION_FLAGS = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0


def rafraichir_path() -> None:
    """Relit le PATH du registre (comme Update-Path dans install.ps1) : un
    outil tout juste installé par winget (ex: ffmpeg) devient visible sans
    rouvrir le terminal. Jarvis et Open WebUI en héritent."""
    if os.name != "nt":
        return
    import winreg

    morceaux = []
    for hive, sous_cle in (
        (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
        (winreg.HKEY_CURRENT_USER, "Environment"),
    ):
        try:
            with winreg.OpenKey(hive, sous_cle) as cle:
                valeur, _ = winreg.QueryValueEx(cle, "Path")
                # REG_EXPAND_SZ : "%SystemRoot%\system32" doit être développé.
                morceaux.append(os.path.expandvars(valeur))
        except OSError:
            pass
    if morceaux:
        # On garde les entrées du PATH courant (ex: venv activé) en plus du registre.
        os.environ["PATH"] = ";".join(morceaux + [os.environ.get("PATH", "")])


def ollama_est_joignable() -> bool:
    try:
        urllib.request.urlopen(OLLAMA_URL, timeout=3)
        return True
    except (urllib.error.URLError, OSError):
        return False


def lire_config() -> tuple[bool, str, int, str, bool]:
    """Lit open_webui.* et update_check.enabled par le venv de Jarvis
    (PyYAML), exactement comme server/main.py, en un seul sous-process."""
    resultat = subprocess.run(
        [
            str(SERVER_PYTHON),
            "-c",
            "import config; print(config.OPEN_WEBUI_ENABLED); "
            "print(config.OPEN_WEBUI_HOST); print(config.OPEN_WEBUI_PORT); "
            "print(config.OPEN_WEBUI_API_KEY); print(config.UPDATE_CHECK_ENABLED)",
        ],
        cwd=SERVER_DIR,
        capture_output=True,
        text=True,
    )
    if resultat.returncode != 0:
        print(resultat.stderr, file=sys.stderr)
        raise RuntimeError("Impossible de lire config.yml (erreur ci-dessus).")
    actif, host, port, api_key, verif_version = resultat.stdout.splitlines()
    return actif == "True", host, int(port), api_key, verif_version == "True"


def _git(*args: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            ["git", *args], cwd=BASE_DIR, capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.SubprocessError):
        return None  # Git absent


def commit_local() -> str | None:
    """SHA du code local : `git rev-parse HEAD` pour un clone, sinon le
    fichier `.version` posé par install.ps1 (installation par .zip)."""
    if (BASE_DIR / ".git").exists():
        resultat = _git("rev-parse", "HEAD")
        if resultat and resultat.returncode == 0:
            return resultat.stdout.strip()
    if COMMIT_LOCAL_PATH.exists():
        return COMMIT_LOCAL_PATH.read_text(encoding="utf-8").strip()
    return None


def commit_distant() -> str | None:
    """SHA du dernier commit de `main` sur GitHub (None si injoignable)."""
    requete = urllib.request.Request(
        COMMIT_DISTANT_URL, headers={"Accept": "application/vnd.github.sha"}
    )
    try:
        with urllib.request.urlopen(requete, timeout=3) as reponse:
            sha = reponse.read().decode("utf-8").strip()
    except (urllib.error.URLError, OSError):
        return None
    return sha if re.fullmatch(r"[0-9a-f]{40}", sha) else None  # jamais affiché tel quel sinon


def est_a_jour(local: str, distant: str, local_contient_distant: bool) -> bool:
    """Même commit, ou local en avance (le commit distant fait partie de son
    historique : travail non poussé, pas un retard)."""
    return local == distant or local_contient_distant


def verifier_version() -> None:
    """Signale si `main` a du nouveau sur GitHub, en comparant des SHA de
    commit — ne met jamais rien à jour (voir ARCHITECTURE.md). Ne bloque
    jamais le démarrage : timeout court, silencieux si pas de réseau ou si la
    version locale est inconnue (ni clone Git, ni `.version`)."""
    local = commit_local()
    if local is None:
        return
    distant = commit_distant()
    if distant is None:
        return
    en_avance = False
    if local != distant and (BASE_DIR / ".git").exists():
        # 0 = le commit distant est un ancêtre de HEAD ; erreur = il nous manque.
        resultat = _git("merge-base", "--is-ancestor", distant, "HEAD")
        en_avance = resultat is not None and resultat.returncode == 0
    if est_a_jour(local, distant, en_avance):
        print(f"✅ Code à jour ({local[:7]}).")
    else:
        print(
            f"⚠️  Nouvelle version disponible sur GitHub (locale : {local[:7]}, "
            f"distante : {distant[:7]}) — https://github.com/pazpop/assistant-vocal-local\n"
        )


def attendre_open_webui_pret(host: str, port: int, timeout: float = 60) -> bool:
    """Sonde /health jusqu'à ce qu'Open WebUI réponde, ou jusqu'au timeout.
    Utilisé uniquement par --purge-webui-memory-on-start, qui a besoin du
    serveur déjà en ligne avant d'appeler son API."""
    limite = time.time() + timeout
    url = f"http://{host}:{port}/health"
    while time.time() < limite:
        try:
            urllib.request.urlopen(url, timeout=3)
            return True
        except (urllib.error.URLError, OSError):
            time.sleep(1)
    return False


def confirmer_ou_quitter(message: str, demander: bool) -> None:
    if not demander:
        return
    reponse = input(f"{message} [y/N] ")
    if reponse.strip().lower() not in ("y", "yes", "o", "oui"):
        sys.exit("Annulé.")


def purger_donnees_open_webui(demander_confirmation: bool) -> None:
    """Supprime openwebui/data/ (historique de chat, comptes, fichiers
    uploadés, index vectoriel) — reset complet. Recréé de zéro au prochain
    lancement d'Open WebUI (nouveau compte admin à recréer)."""
    data_dir = OPENWEBUI_DIR / "data"
    if not data_dir.exists():
        print("Rien à purger : openwebui/data/ n'existe pas.")
        return
    confirmer_ou_quitter(
        f"Supprimer {data_dir} (historique de chat, comptes, fichiers, index vectoriel) ?",
        demander_confirmation,
    )
    shutil.rmtree(data_dir)
    print(f"✅ {data_dir} supprimé — recréé au prochain lancement d'Open WebUI.")


def _effacer_memoire_api(host: str, port: int, api_key: str) -> tuple[bool, str]:
    """DELETE /api/v1/memories/delete/user. Ne lève jamais : renvoie
    (succès, message), l'appelant décide de quitter ou d'avertir."""
    url = f"http://{host}:{port}/api/v1/memories/delete/user"
    requete = urllib.request.Request(
        url, method="DELETE", headers={"Authorization": f"Bearer {api_key}"}
    )
    try:
        with urllib.request.urlopen(requete, timeout=10) as reponse:
            corps = reponse.read().decode()
    except urllib.error.HTTPError as exc:
        return False, f"Échec ({exc.code}) : {exc.read().decode(errors='replace')}"
    except urllib.error.URLError as exc:
        return False, f"Impossible de joindre Open WebUI sur http://{host}:{port} ({exc.reason})."

    if corps.strip() == "true":
        return True, "Mémoire Open WebUI effacée."
    return True, "Rien à effacer (mémoire déjà vide)."


def purger_memoire_open_webui(demander_confirmation: bool) -> None:
    """CLI : python launch.py --purge-webui-memory. Nécessite Open WebUI
    déjà lancé et une clé API valide dans config.yml (open_webui.api_key)."""
    _, host, port, api_key, _ = lire_config()
    if not api_key:
        sys.exit(
            "open_webui.api_key est vide dans config.yml. Génère une clé "
            "dans Open WebUI (Réglages > Compte > Clés API — active d'abord "
            "'Autoriser les clés API' dans Panneau d'administration > "
            "Réglages > Général), puis colle-la dans config.yml."
        )

    confirmer_ou_quitter(
        "Effacer tout ce qu'Open WebUI a mémorisé sur toi (fonction Memory) ?",
        demander_confirmation,
    )

    succes, message = _effacer_memoire_api(host, port, api_key)
    print(("✅ " if succes else "❌ ") + message)
    if not succes:
        sys.exit(1)


def arreter(processus: subprocess.Popen, nom: str) -> None:
    """Termine un sous-process proprement (délai de grâce), puis le tue si
    besoin. Filet de sécurité : Jarvis gère déjà Ctrl+C lui-même (voir
    main.py) — ceci couvre les cas où un enfant ne s'arrête pas de lui-même."""
    if processus.poll() is not None:
        return
    print(f"Arrêt de {nom}...")
    processus.terminate()
    try:
        processus.wait(timeout=10)
    except subprocess.TimeoutExpired:
        processus.kill()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Lance la stack Jarvis (+ Open WebUI en option)."
    )
    parser.add_argument(
        "--purge-webui",
        action="store_true",
        help="Supprime openwebui/data/ (reset complet : historique, comptes, "
        "fichiers, index vectoriel) puis quitte, sans démarrer la stack.",
    )
    parser.add_argument(
        "--purge-webui-memory",
        action="store_true",
        help="Efface uniquement la fonction Memory d'Open WebUI (API "
        "officielle) puis quitte. Nécessite open_webui.api_key dans "
        "config.yml et Open WebUI déjà lancé.",
    )
    parser.add_argument(
        "--purge-webui-on-start",
        action="store_true",
        help="Comme --purge-webui, puis démarre la stack (Open WebUI repart à neuf).",
    )
    parser.add_argument(
        "--purge-webui-memory-on-start",
        action="store_true",
        help="Comme --purge-webui-memory, mais après avoir démarré la stack "
        "(attend qu'Open WebUI réponde, puis purge sa mémoire) au lieu de "
        "quitter. Nécessite open_webui.api_key dans config.yml.",
    )
    parser.add_argument(
        "-y", "--yes", action="store_true", help="Ne pas demander de confirmation avant une purge."
    )
    return parser.parse_args()


def main() -> None:
    rafraichir_path()
    args = parse_args()

    if args.purge_webui:
        purger_donnees_open_webui(demander_confirmation=not args.yes)
        if args.purge_webui_memory:
            # Base (et clé API) déjà effacées, rien de démarré : la purge mémoire est sans objet.
            print(
                "⏸️  --purge-webui-memory ignoré : déjà fait par "
                "--purge-webui ci-dessus (qui efface aussi la clé API)."
            )
        return
    if args.purge_webui_memory:
        purger_memoire_open_webui(demander_confirmation=not args.yes)
        return

    if not SERVER_PYTHON.exists():
        sys.exit(
            "venv de Jarvis introuvable (.venv à la racine). Suis "
            "l'installation du README avant de lancer ce script."
        )

    if not ollama_est_joignable():
        sys.exit(
            "Ollama ne répond pas sur http://localhost:11434. "
            "Installe/démarre Ollama (voir README.md) avant de relancer ce script."
        )

    print("==== Core ====")
    print("✅ Ollama détecté.")

    webui_actif, webui_host, webui_port, webui_api_key, verif_version = lire_config()

    if verif_version:
        verifier_version()

    # Purges : toutes les questions AVANT de lancer quoi que ce soit — elles ne se
    # mélangent pas aux logs de Jarvis, et « non » quitte sans rien laisser tourner.
    webui_lancable = webui_actif and OPENWEBUI_EXE.exists()
    if args.purge_webui_on_start and webui_lancable:
        print("🧹 Purge complète d'Open WebUI avant démarrage (--purge-webui-on-start)...")
        purger_donnees_open_webui(demander_confirmation=not args.yes)

    purger_memoire = False
    if args.purge_webui_memory_on_start and webui_lancable:
        if args.purge_webui_on_start:
            # La purge complète a effacé la base, clé API comprise : tout est déjà vide.
            print(
                "⏸️  Purge de la mémoire ignorée : déjà faite par "
                "--purge-webui-on-start ci-dessus (qui efface aussi la clé "
                "API — regénères-en une si tu veux les deux séparément)."
            )
        elif not webui_api_key:
            print(
                "⚠️  --purge-webui-memory-on-start demandé mais "
                "open_webui.api_key est vide dans config.yml — purge "
                "de la mémoire ignorée."
            )
        else:
            confirmer_ou_quitter(
                "Effacer tout ce qu'Open WebUI a mémorisé sur toi (fonction Memory) ?",
                not args.yes,
            )
            purger_memoire = True

    processus: list[tuple[subprocess.Popen, str]] = []

    jarvis = subprocess.Popen([str(SERVER_PYTHON), "main.py"], cwd=SERVER_DIR)
    processus.append((jarvis, "Jarvis"))
    print("✅ Jarvis lancé.")

    webui: subprocess.Popen | None = None
    if not webui_actif:
        print("⏸️  Open WebUI désactivé (open_webui.enabled: false).")
    elif not OPENWEBUI_EXE.exists():
        print(
            "⚠️  open_webui.enabled: true mais openwebui/.venv-openwebui est "
            "introuvable — voir ARCHITECTURE.md pour l'installer. Jarvis "
            "continue sans Open WebUI."
        )
    else:
        env = os.environ.copy()
        # Base hors du venv (par défaut dans site-packages/, perdue si le venv est recréé).
        env["DATA_DIR"] = str(OPENWEBUI_DIR / "data")
        # CORS (défaut * d'Open WebUI) restreint à sa propre origine en local ; avec
        # 0.0.0.0, l'origine du navigateur distant est imprévisible : défaut conservé.
        if webui_host == "127.0.0.1":
            env["CORS_ALLOW_ORIGIN"] = f"http://127.0.0.1:{webui_port}"
        webui = subprocess.Popen(
            [str(OPENWEBUI_EXE), "serve", "--host", webui_host, "--port", str(webui_port)],
            cwd=OPENWEBUI_DIR,
            env=env,
            creationflags=CREATION_FLAGS,
        )
        processus.append((webui, "Open WebUI"))
        print(f"✅ Open WebUI lancé sur http://{webui_host}:{webui_port} (fenêtre séparée)")

        if purger_memoire:
            print("🧹 Attente d'Open WebUI pour purger sa mémoire (--purge-webui-memory-on-start)...")
            if attendre_open_webui_pret(webui_host, webui_port):
                succes, message = _effacer_memoire_api(webui_host, webui_port, webui_api_key)
                print(("✅ " if succes else "⚠️  ") + message)
            else:
                print("⚠️  Open WebUI n'a pas répondu à temps — purge de la mémoire ignorée.")

    print("\nCtrl+C pour tout arrêter proprement.\n")

    try:
        while True:
            if jarvis.poll() is not None:
                # Jarvis est le composant essentiel : s'il s'arrête (erreur
                # ou Ctrl+C), on arrête le reste avec lui.
                break
            if webui is not None and webui.poll() is not None:
                print("⚠️  Open WebUI s'est arrêté de façon inattendue — Jarvis continue.")
                webui = None
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for proc, nom in processus:
            arreter(proc, nom)


if __name__ == "__main__":
    main()
