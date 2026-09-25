# Roadmap

Ce qui reste à faire. L'existant (et le pourquoi des choix) est dans
[ARCHITECTURE.md](ARCHITECTURE.md) ; l'historique, dans git.

## Prioritaire

### Dédoublonnage des docs (suite)

- [ ] Purges Open WebUI, contenu d'`install.ps1` et description de l'API
  satellite restent partiellement répétés entre README, ARCHITECTURE et
  `config.yml.example` : ne garder qu'ARCHITECTURE, avec des renvois.

### Suites de la revue du 2026-09-25

- [ ] Tests pour le reste de `launch.py` (seule la version est couverte) : arguments, refus
  des deux purges combinées, lecture de la version.
- [ ] Alertes météo : les diffuser aussi aux satellites (aujourd'hui, seul le
  PC les annonce). Même mécanisme que les minuteurs (`BoiteNotifications`).
- [ ] Sécurité : limiter les essais de clé API.
- [ ] Mesurer `beam_size=1` pour le STT (latence).
- [ ] Routage par sous-chaîne (`trigger.py`) : normaliser accents/apostrophes
  une fois, plutôt que lister les variantes à la main.

## Mineurs (revue du 2026-09-25)

- [ ] Alerte météo déjà active au démarrage : annoncée au premier sondage
  (15 min plus tard) ; et marquée « vue » avant l'annonce, donc perdue si la
  synthèse échoue.
- [ ] Registre unique des modules dans `main.py` : la liste (outils,
  exécuteur, déclencheur) est écrite deux fois (`construire_routes_directes`
  et `construire_outils`).
- [ ] `launch.py` : respecter `OLLAMA_HOST` (codé en dur sur
  `localhost:11434`) et fermer la réponse de `urlopen`.
- [ ] CI : référencer les actions GitHub par SHA plutôt que par tag.
- [ ] Écho de la salutation : le micro écoute pendant « Oui, comment puis-je
  vous aider ? » ; à tester sans casque.
- [ ] Charger les modèles au démarrage en parallèle (STT, TTS, VAD, mot-clé).
- [ ] Import paresseux de FastAPI/uvicorn quand `satellite.enabled: false`.

## Satellites Raspberry Pi

Procédure matériel/OS/pilotes :
[satellite/RASPBERRY_PI_SETUP.md](satellite/RASPBERRY_PI_SETUP.md).

- [ ] Conversation continue côté satellite (réécouter après une réponse sans
  redire « Hey Jarvis »).
- [ ] Vrai VAD sur le Pi (`pysilero-vad`, à vérifier sans PyTorch en Python
  3.13 aarch64) à la place du seuil de volume adaptatif.
- [ ] Annulation d'écho / interruption pendant que Jarvis parle.
- [ ] **TLS** entre satellite et serveur (voulu, pas urgent) : aujourd'hui
  HTTP en clair, clé API et audio compris. Deux voies :
  - sans code (rapide, ~30 min) : Tailscale/WireGuard entre le Pi et le PC,
    puis `satellite.host` sur l'adresse du tunnel ;
  - TLS dans le code : certificat auto-signé côté serveur (uvicorn
    `ssl_certfile`/`ssl_keyfile`), distribué au Pi, `server.verify_ssl`/CA
    côté client (comme pour Home Assistant).
- [ ] Une clé API par satellite, zone déduite de la clé (aujourd'hui `X-Zone`
  est déclaratif : un satellite peut se faire passer pour un autre).
- [ ] Découverte automatique du serveur (mDNS).

## Installation

- [ ] `install.ps1` demande la ville et renseigne `location:` dans
  `config.yml`. Ne demander que la ville (pas « ville + province », propre au
  Canada) : le géocodage Open-Meteo résout `geocode_query`/`timezone`.
- [ ] Documenter la mise à jour d'une installation existante : `install.ps1`
  ne met pas le code à jour, et `launch.py` signale seulement qu'une nouvelle
  version existe.

## Module musique

- [ ] Jouer une chanson à la voix : « Hey Jarvis, peux-tu mettre la chanson
  XXX de l'artiste YYY ». Module `music.py` sur le modèle de `weather.py`
  (outil LLM `jouer_chanson(titre, artiste)`, `music.enabled`, déclencheur
  par mots-clés). À trancher avant de coder :
  - **Source** : lecteur local (fichiers musicaux du PC, recherche par
    titre/artiste, sans compte) ; Spotify (compte Premium + API, contrôle d'un
    appareil existant) ; ou YouTube Music/`yt-dlp` (gratuit mais zone grise
    côté conditions d'utilisation).
  - **Lecture** : sur le PC, et/ou sur le satellite (audio diffusé au Pi,
    même mécanisme que les notifications).
  - **Commandes associées** : pause, reprise, suivant, volume, stop. Le
    micro reste ouvert pendant la lecture : baisser le volume (ou couper)
    pendant l'écoute du mot-clé pour ne pas le brouiller.
  - **Fiabilité** : titres et noms d'artistes mal transcrits par le STT ;
    prévoir une recherche approximative et une confirmation orale
    (« Je mets X de Y »).

## Idées à l'étude

- **Moteur de recherche Internet** (API Brave Search, gratuite jusqu'à 2000
  requêtes/mois), sur le modèle de `weather.py`. Risque : qwen2.5:7b peut
  mal interpréter des extraits. Prototyper, tester sur des questions
  factuelles, puis décider.
- **Contrôle du PC** (ouvrir applications/sites par la voix).
- **ComfyUI** (génération d'images), non prioritaire : la VRAM (6-8 Go) peut
  être incompatible avec Jarvis actif sur 10 Go.
- **Intégration Wyoming** (protocole de Home Assistant Voice), pour utiliser
  d'autres satellites que le client maison.
- **Bench d'un modèle plus adapté au français + appels d'outils** que
  qwen2.5:7b.

## Limites connues

- La CI (runners sans GPU) ne couvre jamais `stt.device: cuda`, seulement le
  CPU.
- Bug amont d'Open WebUI (`KeyError: 'model'` dans `background_tasks_handler`,
  génération automatique du titre) : non fatal, rien à corriger de notre côté.
