# Roadmap

Ce qui reste à faire. L'existant (et le pourquoi des choix) est dans
[ARCHITECTURE.md](ARCHITECTURE.md) ; l'historique, dans git.

## Prioritaire

### Suites de la revue du 2026-09-25

- [ ] Tests pour le reste de `launch.py` (seule la version est couverte) :
  arguments, refus des deux purges combinées.
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

Objectif : « Hey Jarvis, peux-tu mettre la chanson XXX de l'artiste YYY »,
lue **sur le satellite**. Module `music.py` sur le modèle de `weather.py`
(outil LLM `jouer_chanson(titre, artiste)`, `music.enabled`, déclencheur par
mots-clés), avec une source choisie dans `config.yml` (`music.provider`).

**Sources, par ordre** :
1. **Subsonic/Navidrome** (choisi pour commencer) : API ouverte (HTTP +
   JSON), recherche floue côté serveur (`search3`), flux sans DRM (`stream`) ;
   URL, utilisateur et mot de passe/jeton dans `config.yml`. Navidrome est le
   serveur le plus léger (PC, NAS ou Pi).
2. Fichiers locaux du Pi, avec recherche floue (sans serveur).
3. Spotify Premium via `raspotify` (Spotify Connect sur le Pi, piloté par
   l'API Web).
4. Plex : API moins pratique pour la musique, à faire si besoin.
5. **Apple Music : écarté** : MusicKit demande un compte développeur payant et
   la lecture est protégée (DRM), inutilisable depuis un Pi.

**Lecture** : le lecteur (`mpv`, avec pause/volume par IPC) tourne sur le
satellite, qui lit directement le flux de la source. Le serveur envoie des
commandes au satellite (extension du canal `GET /notifications`, à passer de
3 s à ~1 s de réactivité).

**Commandes** : pause, reprise, suivant, volume, stop.

**Mot-clé pendant la musique** : le micro reste ouvert ; à « Hey Jarvis », le
satellite met la musique en pause lui-même (instantané, sans serveur) et la
reprend après la conversation, sauf si une commande musicale a été donnée.
Risque : sans annulation d'écho, le HAT détecte moins bien le mot-clé à volume
élevé ; baisser le volume, à essayer sur le matériel.

**Titres (important)** : le STT déforme titres et artistes. Recherche floue
(côté Subsonic), confirmation orale (« Je mets X de Y »), et piste à mesurer :
passer les noms d'artistes de la bibliothèque à Whisper (`initial_prompt`).

- [ ] Fournisseur Subsonic/Navidrome (recherche + URL de flux).
- [ ] Lecteur `mpv` sur le satellite et canal de commandes serveur → satellite.
- [ ] Outil LLM `jouer_chanson`, commandes de contrôle, confirmation orale.
- [ ] Pause au mot-clé, reprise après la conversation.
- [ ] Autres fournisseurs (fichiers locaux, Spotify/raspotify, Plex).

## Idées à l'étude

- **Moteur de recherche Internet** (API Brave Search, gratuite jusqu'à 2000
  requêtes/mois), sur le modèle de `weather.py`. Risque : qwen2.5:7b peut
  mal interpréter des extraits. Prototyper, tester sur des questions
  factuelles, puis décider.
- **Prévisions plus lointaines** (« ce week-end », « lundi », une semaine) :
  aujourd'hui seuls demain et après-demain sont gérés.
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
