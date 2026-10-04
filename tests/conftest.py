"""Configuration pytest partagée : rend server/ importable depuis les tests,
et s'assure qu'un config.yml existe (server/config.py refuse de démarrer
sans lui). Sur une machine qui a déjà le sien (usage normal), on ne touche à
rien ; sur une machine fraîche/CI, on le crée depuis le modèle fourni pour
que les tests tournent sans configuration manuelle préalable.
"""
import shutil
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "server"))

_config_yml = RACINE / "config.yml"
_exemple = RACINE / "config.yml.example"
if not _config_yml.exists() and _exemple.exists():
    shutil.copy(_exemple, _config_yml)
