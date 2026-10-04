"""Configuration pytest pour les tests du client satellite : rend
satellite/ importable, et crée satellite/config.yml depuis le modèle si
absent (même logique que tests/conftest.py côté serveur).

À exécuter en tant qu'invocation pytest séparée de `pytest tests/` :
server/ et satellite/ définissent chacun un module "config"/"audio_io" —
les mélanger dans le même process pytest ferait retourner le mauvais module
à l'un des deux (sys.modules est un cache global par nom d'import, pas par
dossier). Voir satellite/README.md > Tests.
"""
import shutil
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

_config_yml = RACINE / "config.yml"
_exemple = RACINE / "config.yml.example"
if not _config_yml.exists() and _exemple.exists():
    shutil.copy(_exemple, _config_yml)
