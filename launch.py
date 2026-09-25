"""Lance la stack Jarvis (+ Open WebUI en option) en un seul script, sans
Docker : chaque composant tourne dans son propre venv, comme processus
séparé de ce script.

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

# Robuste face aux emojis (✅/⚠️/⏸️) même dans une console dont l'encodage
# par défaut n'est pas UTF-8 (ex: cp1252 sur certaines installations
# Windows) — sans ça, le premier print() avec emoji fait planter le script.
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

# Ouvre Open WebUI dans sa propre fenêtre de console plutôt que de mélanger
# ses logs (verbeux : migrations de base, requêtes HTTP) avec ceux de
# Jarvis dans la même fenêtre. Jarvis reste dans la fenêtre principale —
# c'est lui l'expérience interactive qu'on surveille en direct.
CREATION_FLAGS = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0


def rafraichir_path() -> None:
    """Relit le PATH depuis le registre Windows (comme Update-Path dans
    install.ps1, côté Python cette fois) : un outil tout juste installé via
    winget (ex: ffmpeg pour Open WebUI) reste invisible tant qu'aucun
    processus n'a relu cette valeur — sans ça, il faudrait fermer et
    rouvrir le terminal avant de relancer launch.py. Jarvis et Open WebUI
    héritent de l'environnement de ce process, donc les corriger ici suffit
    pour les deux."""
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
    """Lit depuis config.yml ce dont launch.py a besoin (open_webui.* +
    update_check.enabled), via le venv de Jarvis (déjà équipé de PyYAML)
    plutôt que de dupliquer un parseur YAML ici — config.yml reste l'unique
    source de vérité, lue exactement comme le fait server/main.py. Un seul
    sous-process pour tout, plutôt qu'un par réglage (chaque appel relance
    Python)."""
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
    """Appelle l'API officielle de suppression de la mémoire Open WebUI
    (DELETE /api/v1/memories/delete/user). Ne lève jamais : renvoie
    (succès, message) — appelée aussi bien par --purge-webui-memory (qui
    quitte sur échec) que par la purge automatique au démarrage (qui doit
    seulement avertir, jamais interrompre le reste du lancement)."""
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
        description="Lance la stack Jarvis (+ Open WebUI en option), sans Docker."
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
        help="Comme --purge-webui, mais démarre ensuite la stack normalement "
        "au lieu de quitter (Open WebUI redémarre à neuf, à taper "
        "explicitement à chaque fois — volontairement pas un réglage de "
        "config.yml).",
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
            # --purge-webui vient d'effacer webui.db en entier (donc la clé
            # API) et ne démarre rien : --purge-webui-memory échouerait de
            # toute façon (serveur injoignable, clé invalide) — et est
            # redondant, tout est déjà vide.
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

    # Purge (et sa confirmation interactive) AVANT de lancer Jarvis, pour que
    # la question ne se mélange pas à ses logs.
    if args.purge_webui_on_start and webui_actif and OPENWEBUI_EXE.exists():
        print("🧹 Purge complète d'Open WebUI avant démarrage (--purge-webui-on-start)...")
        purger_donnees_open_webui(demander_confirmation=not args.yes)

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
        # Par défaut, Open WebUI écrit sa base (comptes, historique de chat)
        # dans site-packages/, à l'intérieur du venv — perdue si le venv est
        # recréé. On la sort dans un dossier dédié, comme models/ pour Jarvis.
        env["DATA_DIR"] = str(OPENWEBUI_DIR / "data")
        # Open WebUI accepte par défaut les requêtes cross-origin depuis
        # n'importe quel site (CORS_ALLOW_ORIGIN=*) — un site malveillant
        # ouvert dans le même navigateur pourrait interroger l'API locale.
        # On la restreint à sa propre origine quand host=127.0.0.1 (le cas
        # par défaut, un seul navigateur sur cette machine) ; sans effet si
        # l'utilisateur a choisi 0.0.0.0 pour y accéder depuis un autre
        # appareil du réseau — l'origine du navigateur distant n'est alors
        # pas prévisible à l'avance.
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

        if args.purge_webui_on_start and args.purge_webui_memory_on_start:
            # --purge-webui-on-start vient d'effacer webui.db en entier, donc
            # aussi la clé API (stockée dans la base, liée au compte) : un
            # appel avec la clé de config.yml échouerait (401, compte
            # disparu) sur cette instance neuve — et de toute façon, tout est
            # déjà vide.
            print(
                "⏸️  Purge de la mémoire ignorée : déjà faite par "
                "--purge-webui-on-start ci-dessus (qui efface aussi la clé "
                "API — regénères-en une si tu veux les deux séparément)."
            )
        elif args.purge_webui_memory_on_start:
            if not webui_api_key:
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
