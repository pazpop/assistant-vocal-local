# Client satellite (Raspberry Pi)

Client léger : mot-clé "Hey Jarvis" + micro + haut-parleur. Tout le
traitement (transcription, LLM, outils, synthèse vocale) reste sur le PC qui
fait tourner Jarvis, via `server/satellite_api.py` — voir
[ARCHITECTURE.md](../ARCHITECTURE.md#api-satellite).

## Prérequis

- Matériel choisi, **Raspberry Pi OS 64 bits** installé (les dépendances
  Python `onnxruntime`/`tflite-runtime` n'ont de paquets prêts à l'emploi
  que pour cette architecture), pilotes du HAT micro/haut-parleur
  installés — voir [RASPBERRY_PI_SETUP.md](RASPBERRY_PI_SETUP.md) si ce
  n'est pas déjà fait.
- Python 3.11 (Raspberry Pi OS Bookworm) ou 3.13 (Trixie), déjà présent :
  `python3 --version`. L'installation ci-dessous fonctionne sur les deux
  (openwakeword y est installé sans `tflite-runtime`, indisponible en 3.13).
- L'API satellite activée côté serveur (`satellite.enabled: true` dans le
  `config.yml` du PC, avec une `api_key` définie) — voir
  [ARCHITECTURE.md](../ARCHITECTURE.md#api-satellite).

## Installation

```bash
sudo apt update
sudo apt install -y python3-venv libportaudio2
git clone https://github.com/pazpop/assistant-vocal-local.git
cd assistant-vocal-local/satellite
python3 -m venv .venv
source .venv/bin/activate
pip install --no-deps openwakeword==0.6.0   # sans ses dépendances : voir requirements.txt
pip install -r requirements.txt
cp config.yml.example config.yml
```

Édite `config.yml` :

- `server.url` : adresse IP du PC + `:8791/assistant` (ex:
  `http://192.168.1.50:8791/assistant`) — trouve l'IP du PC avec `ipconfig`
  (Windows) ou `hostname -I` (Linux/macOS).
- `server.api_key` : la même valeur que `satellite.api_key` dans le
  `config.yml` du serveur (généré avec `python generate_api_key.py` côté
  serveur).

## Lancement

```bash
source .venv/bin/activate
python main.py
```

Dis "Hey Jarvis" — un bip confirme que le satellite écoute, puis joue la
réponse une fois reçue. Ctrl+C pour quitter.

`python main.py --debug-audio` affiche le score du mot-clé et le niveau
audio en direct, pour calibrer `wake_word.threshold`/`audio.silence_threshold`
dans `config.yml`.

## Démarrage automatique (systemd)

Une fois que `python main.py` fonctionne correctement lancé à la main
(teste d'abord — plus simple à déboguer sans systemd dans l'équation),
fais-le démarrer automatiquement à chaque boot du Pi, avec redémarrage
automatique s'il plante.

Depuis `satellite/` (le `.venv` doit déjà exister, voir
[Installation](#installation)) :

```bash
sudo tee /etc/systemd/system/jarvis-satellite.service > /dev/null <<EOF
[Unit]
Description=Client satellite Jarvis (mot-clé + micro + haut-parleur)
After=network-online.target sound.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$(pwd)
ExecStart=$(pwd)/.venv/bin/python main.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now jarvis-satellite.service
```

`$USER`/`$(pwd)` sont substitués par le shell au moment de créer le fichier
— rien à éditer manuellement, à condition de lancer ce bloc depuis
`satellite/` avec le bon utilisateur déjà connecté.

**Vérifier que ça tourne** :

```bash
sudo systemctl status jarvis-satellite.service   # actif/inactif, dernières lignes
journalctl -u jarvis-satellite.service -f        # logs en direct (Ctrl+C pour quitter)
```

**Arrêter le démarrage automatique** (sans désinstaller le client) :

```bash
sudo systemctl disable --now jarvis-satellite.service
```

**Le micro/haut-parleur n'est pas encore prêt juste après le boot ?**
`main.py` capture déjà toute erreur dans sa boucle principale (voir
`except Exception` dans `main.py`) : un échec ponctuel d'ouverture du
périphérique audio au démarrage affiche `[erreur] ...` et réessaie tout
seul au tour suivant, sans faire planter le service.

## Tests

```bash
pip install pytest
pytest satellite/tests/
```

Toujours en séparé de `pytest tests/` (les tests du serveur) : les deux
définissent chacun un module `config`/`audio_io` — les lancer dans le même
process pytest ferait retourner le mauvais module à l'un des deux (voir
`satellite/tests/conftest.py`).

## Limites connues

- **Un tour par mot-clé** : pas de conversation continue (il faut redire
  "Hey Jarvis" à chaque question) — simplification volontaire pour cette
  première version, voir [ROADMAP.md](../ROADMAP.md#satellites-raspberry-pi).
- **Détection de fin de parole par seuil de volume (RMS)**, pas par VAD
  contrairement au serveur — moins robuste au bruit de fond (pourquoi :
  [ARCHITECTURE.md](../ARCHITECTURE.md#client-satellite)). Calibre
  `audio.silence_threshold` si l'enregistrement se coupe trop tôt ou trop
  tard.
