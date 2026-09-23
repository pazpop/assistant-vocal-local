# Roadmap

Fonctionnalités déjà intégrées et prochaines étapes. Détail technique de
l'existant : [ARCHITECTURE.md](ARCHITECTURE.md).

## Fonctionnalités intégrées

- Mot-clé "Hey Jarvis" (openWakeWord) + VAD (Silero)
- Transcription locale GPU (faster-whisper) + LLM local (Ollama/Qwen2.5:7b) + synthèse vocale (Piper)
- Pipeline LLM → TTS en streaming (phrase par phrase, sans attendre la réponse complète)
- Conversation continue (réécoute sans redire le mot-clé, historique en RAM uniquement)
- Domotique (Home Assistant, API REST locale) · Météo (Open-Meteo) · Alertes météo proactives (Environnement Canada) · Minuteurs · Date/heure · Panneau de ressources local
- Chaque module optionnel activable/désactivable de façon uniforme (`enabled: true/false` dans `config.yml`)

## À venir

### Interface web de conversation (Open WebUI)

Actuellement déployé en Docker, connecté à Ollama natif (`host.docker.internal:11434`).

- [ ] Migrer vers un venv Python dédié (`openwebui/.venv-openwebui/`) plutôt que Docker — évite d'imposer Docker Desktop pour un seul conteneur. Conflit vérifié qui empêcherait de le mettre dans le même venv que Jarvis : Open WebUI épingle `onnxruntime==1.26.0`, Jarvis épingle `onnxruntime==1.30.0` (utilisé par `openwakeword`/`vad.py`) — deux venvs séparés obligatoires.
- [ ] Nettoyer le system prompt de `qwen2.5-coder` (contaminé par des exemples d'appels d'outils Jarvis, le modèle imite ces exemples au lieu de coder) — créer un modèle personnalisé dans Open WebUI (**Espace de travail > Modèles**) avec son propre system prompt, plutôt que de modifier la config globale ou la base SQLite directement.

### Lancement simplifié

Objectif : rendre le démarrage accessible à quelqu'un qui n'est pas développeur, avec les modules optionnels faciles à activer/désactiver.

- [ ] `launch.py` à la racine (stdlib uniquement) : vérifie qu'Ollama répond, lance Jarvis (`server/.venv`), lance Open WebUI en option (`openwebui/.venv-openwebui`) — arrêt propre de tous les sous-process sur Ctrl+C.
- [ ] Décider le mécanisme de toggle pour Open WebUI : clé `open_webui.enabled` dans `config.yml` (cohérent avec les autres modules) ou flag CLI (`--with-webui`) — arbitrage en attente.

### CI — compatibilité Linux

- [ ] Job GitHub Actions sur `ubuntu-latest` : `pip install -r requirements.txt` (lignes CUDA commentées) + `pytest tests/`. Valide que le code Python tourne sur Linux, sans Docker ni build d'image.
- **Limite à documenter, pas à découvrir plus tard** : les runners gratuits GitHub n'ont pas de GPU — cette CI ne validera jamais le vrai chemin `stt.device: cuda`, seulement le fallback CPU.

### Satellites Raspberry Pi

`satellite/` accueillera un client léger (mot-clé + micro + haut-parleur) qui
envoie l'audio au serveur et joue la réponse reçue, le serveur gardant
`stt.py`/`llm.py`/`tts.py`/`home_assistant.py` derrière une petite API
(FastAPI par exemple). Le [panneau de ressources](ARCHITECTURE.md#panneau-de-ressources)
(`server/dashboard.py`) est un premier pas dans cette direction : un serveur
HTTP local à étendre plus tard, plutôt qu'un serveur séparé.

À ne découper en client/serveur réseau que lorsqu'un vrai second client
existera — pas par anticipation (voir [Décisions écartées](#décisions-écartées)
pour le raisonnement équivalent côté Docker).

- [ ] Serveur API (FastAPI) exposant STT+LLM+TTS+domotique en un seul endpoint
- [ ] Client satellite minimal pour Raspberry Pi (wake word + micro + speaker)
- [ ] Découverte automatique du serveur sur le réseau local (mDNS)
- [ ] Support multi-satellites (un nom de zone par Pi : "Hey Jarvis" partout, réponse localisée)

### Moteur de recherche Internet (à l'étude)

Piste envisagée : un outil de recherche web via l'**API Brave Search** (clé
gratuite jusqu'à 2000 requêtes/mois), suivant l'architecture de
`weather.py` (module + outil LLM + activation via `config.yml`).

Pas encore décidé si ça vaut le coup : le risque principal est qu'un petit
modèle local comme qwen2.5:7b interprète ou mélange mal des extraits de
résultats de recherche, donnant une réponse imprécise sur des faits — à
valider par des tests concrets avant de trancher.

- [ ] Prototyper l'outil avec l'API Brave Search
- [ ] Tester la fiabilité des réponses du LLM sur des questions factuelles (scores, actualités, chiffres)
- [ ] Décider de l'intégrer ou non selon ces résultats

### Contrôle du PC

Nouveau module permettant de demander à Jarvis d'exécuter des actions sur le
PC. Exemple : *"Hey Jarvis, ouvre Firefox, va sur YouTube et lance la
chanson Kammthaar de Ultra Vomit."*

- [ ] Module de contrôle du PC (actions système, ouverture d'applications/sites)

### ComfyUI (génération d'images) — non prioritaire

Testé une première fois puis désinstallé après validation.

- [ ] Réintégrer ComfyUI (launcher Windows ou Docker isolé, indépendant de la décision "pas de Docker" ci-dessous puisqu'il n'a aucune interaction avec le reste de la stack) + SDXL + LoRA Lightning
- [ ] Intégration Open WebUI (**Paramètres > Images > ComfyUI Base URL**)
- **Attention** : VRAM (6-8 Go) potentiellement incompatible avec Jarvis actif sur la RTX 3080 (10 Go) — cohabitation à valider avant d'aller plus loin.

## Décisions écartées

### Conteneurisation complète de la stack (Docker)

Proposition initiale (2026-09-23) : `jarvis-api` + Ollama + Open WebUI en 3
conteneurs Docker + un client audio hôte. Écartée après analyse :

- **Ollama en conteneur** : déjà natif et fonctionnel — le faire tourner en
  Docker sur Windows exigerait le passthrough GPU du backend WSL2 de Docker
  Desktop + `nvidia-container-toolkit`, une couche de fragilité en plus pour
  aucun bénéfice fonctionnel.
- **`jarvis-api` (STT GPU) en conteneur** : même problème de passthrough
  GPU, avec en prime le risque de désaccord de versions entre l'image et ce
  qu'attend `ctranslate2` (`nvidia-cublas-cu12`/`nvidia-cudnn-cu12`). Une CI
  sans GPU (runners gratuits GitHub) ne validerait de toute façon jamais le
  vrai chemin CUDA — seulement un fallback CPU, avec une perte de
  performance réelle sur `faster-whisper` (estimation en discussion, non
  mesurée : ~1-3s au lieu de <0,5s par transcription courte, int8/CPU vs
  float16/GPU).
- **Open WebUI** : seul composant où Docker apportait un vrai service
  (isolation d'un webapp aux dépendances lourdes), mais imposer Docker
  Desktop (WSL2, overhead mémoire permanent) pour un seul conteneur n'est
  pas justifié — remplacé par un venv Python natif dédié (voir
  [ci-dessus](#interface-web-de-conversation-open-webui)).
- **CI/CD par image Docker + ghcr.io** : remplacée par un simple job pytest
  sur `ubuntu-latest` (voir [CI — compatibilité Linux](#ci--compatibilité-linux)),
  qui valide la même chose (le code Python tourne sur Linux) sans le coût du
  build d'image.

## Fait

- **2026-09-23** — Chaque module optionnel (`home_assistant`, `weather`,
  `alerts`, `dashboard`) utilise une clé `enabled` uniforme dans
  `config.yml`, avec rétrocompatibilité pour les installations existantes
  (déduite de `token`/`feed_url` si la clé est absente).
- **2026-09-23** — Documentation réorganisée : README raccourci, détail
  technique dans `ARCHITECTURE.md`, suivi des fonctionnalités dans ce
  fichier.
