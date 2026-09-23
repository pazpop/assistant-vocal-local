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

- [x] Migré vers un venv Python dédié (`openwebui/.venv-openwebui/`, 2026-09-23) plutôt que Docker — évite d'imposer Docker Desktop pour un seul conteneur. Conflit vérifié qui empêche de le mettre dans le même venv que Jarvis : Open WebUI épingle `onnxruntime==1.26.0`, Jarvis épingle `onnxruntime==1.30.0` (utilisé par `openwakeword`/`vad.py`).
- [x] Base de données (comptes, historique de chat) redirigée hors du venv via `DATA_DIR` (par défaut, Open WebUI l'écrit dans `site-packages/`, perdue si le venv est recréé).
- [ ] Nettoyer le system prompt de `qwen2.5-coder` (contaminé par des exemples d'appels d'outils Jarvis, le modèle imite ces exemples au lieu de coder) — créer un modèle personnalisé dans Open WebUI (**Espace de travail > Modèles**) avec son propre system prompt, plutôt que de modifier la config globale ou la base SQLite directement. Reste à faire manuellement dans l'interface, aucune automatisation possible côté dépôt.

### Lancement simplifié

Objectif : rendre le démarrage accessible à quelqu'un qui n'est pas développeur, avec les modules optionnels faciles à activer/désactiver.

- [x] `launch.py` à la racine (stdlib uniquement, 2026-09-23) : vérifie qu'Ollama répond, lance Jarvis (`.venv` à la racine), lance Open WebUI en option (`openwebui/.venv-openwebui`) — arrêt propre de tous les sous-process sur Ctrl+C. Testé de bout en bout (Ollama détecté, Jarvis démarré et resté stable, Open WebUI correctement ignoré/lancé selon `open_webui.enabled`).
- [x] Toggle Open WebUI : clé `open_webui.enabled` (+ `host`/`port`) dans `config.yml`, cohérent avec les autres modules.
- [x] CORS restreint (2026-09-23) : Open WebUI avertit au démarrage que `CORS_ALLOW_ORIGIN=*` accepte les requêtes de n'importe quel site — `launch.py` le restreint à sa propre origine quand `open_webui.host` vaut `127.0.0.1` (le défaut). Testé : l'avertissement disparaît.
- [x] ffmpeg (2026-09-23) : ajouté comme troisième paquet confirmé dans `install.ps1` (même principe que Python/Ollama) — pas requis par Jarvis, seulement par les fonctions audio propres à Open WebUI (`pydub`, avertissement `RuntimeWarning` sinon). Testé : installation réelle via winget confirmée, détecté correctement au relancement.
- **Bug trouvé et corrigé en testant** : `main.py` et `launch.py` plantaient (`UnicodeEncodeError`) sur les emojis (✅/⚠️/⏸️) dès qu'ils tournent dans une console qui ne détecte pas l'UTF-8 (ex: cp1252) — typiquement quand `main.py` est lancé comme sous-process par `launch.py` plutôt que directement dans un terminal interactif. Corrigé par un `sys.stdout.reconfigure(encoding="utf-8")` dans les deux fichiers.
- [x] `python launch.py --purge-webui` (reset complet, testé) et `--purge-webui-memory` (fonction Memory uniquement, via l'API officielle `DELETE /api/v1/memories/delete/user` — vérifiée dans le code source d'Open WebUI installé, pas une supposition). Les deux avec confirmation (`--yes` pour l'ignorer).
- [x] Purge combinée au démarrage via `--purge-webui-on-start`/`--purge-webui-memory-on-start` — testée (marqueur factice supprimé, base recréée, stack démarrée normalement ensuite). Volontairement des options de lancement, pas des clés dans `config.yml` (envisagé un temps, puis écarté : un interrupteur qui purge silencieusement à chaque démarrage est le genre de réglage qu'on oublie d'avoir activé).
- [x] `install.ps1` (2026-09-23) : installe Python/Ollama via winget (confirmation individuelle pour chacun), récupère le dépôt en `.zip` (pas besoin de Git), crée le venv, installe les dépendances, tire le modèle LLM et la voix Piper — puis affiche la commande pour lancer Jarvis, sans le faire lui-même. Testé de bout en bout sur une machine où tout était déjà installé (détection correcte, aucune install redéclenchée). Bug trouvé en testant : `Invoke-WebRequest` pouvait rester bloqué sans lever d'exception lors de la vérification qu'Ollama répond — remplacé par une connexion TCP brute (`TcpClient`), plus fiable.
- [x] Détection GPU (2026-09-23) : NVIDIA/AMD/aucun, message clair au tout début du script (`Get-CimInstance Win32_VideoController`), purement informatif. Testé (RTX 3080 correctement détectée).
- [x] `install.bat` (2026-09-23) : double-clic direct (les `.ps1` ne le sont jamais sous Windows) pour qui a déjà le dépôt sur son disque — appelle `install.ps1` avec `-ExecutionPolicy Bypass`. Testé via `cmd /c` depuis un autre répertoire. Alternative sans fichier supplémentaire documentée dans le README : clic droit sur `install.ps1` → "Exécuter avec PowerShell".
- [x] Fenêtre gardée ouverte succès/erreur (2026-09-23) : `Quitter` (pause + exit) partout, `try/catch` global. Bug trouvé en implémentant : `$ErrorActionPreference = "Stop"` rendait `Write-Error` bloquant, donc le code juste après (dont la pause) n'était jamais atteint — corrigé (`throw` + `catch` englobant). Testé : chemin succès et chemin échec affichent tous les deux le message final puis attendent une touche.
- [ ] `install.ps1` demande la ville à l'utilisateur et ajuste `config.yml` (`location:`) directement, plutôt que de le laisser en `Montréal` par défaut avec un simple rappel à la fin.
  - **Attention à l'international** : l'exemple actuel de `config.yml.example` utilise `geocode_query: "Montréal, QC"` (ville + province, spécifique au Canada). Ne pas demander "ville + province" comme champ générique — en France par exemple, il n'y a pas de province. La bonne approche est probablement de ne demander que la ville (en texte libre, avec pays optionnel si ambigu) et de laisser le géocodage Open-Meteo (déjà utilisé par `weather.geocoder()` à l'exécution) résoudre `geocode_query`/`timezone` tout seul, plutôt que de faire deviner un format administratif à l'utilisateur.
- [x] Vérification de version (2026-09-23) : `launch.py` compare `VERSION` (racine, une date) à celui de GitHub au démarrage — un message dans les deux cas (`✅ Code à jour` ou `⚠️ Nouvelle version disponible`), jamais de mise à jour automatique (choix explicite : détecter, pas corriger). Pas basé sur Git/commits (`install.ps1` n'en dépend pas) — un simple fichier texte comparé à sa version distante, désactivable (`update_check.enabled: false`). Testé (cas à jour, en retard, et réseau indisponible — silencieux uniquement dans ce dernier cas).
- [x] Open WebUI dans sa propre fenêtre de console (2026-09-23) : `launch.py` utilise `subprocess.CREATE_NEW_CONSOLE`, ses logs (verbeux) ne se mélangent plus avec ceux de Jarvis. Jarvis reste dans la fenêtre principale. Testé (nouvelle fenêtre confirmée à l'écran).
- [x] `launch.py` relit le `PATH` depuis le registre à chaque démarrage (2026-09-23) : ffmpeg installé via `install.ps1` restait invisible pour Open WebUI (`RuntimeWarning: Couldn't find ffmpeg or avconv`) tant que le terminal utilisé pour lancer `launch.py` n'était pas rouvert — le même piège que celui déjà documenté pour `install.ps1` lui-même, mais qui touchait cette fois une session différente. Testé : `shutil.which('ffmpeg')` passe de `None` à un chemin valide après l'appel, et le warning disparaît réellement des logs d'Open WebUI.

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

- **2026-09-23** — `install.ps1` : installation en une commande
  (`irm ... | iex`), sans prérequis (Python/Ollama installés via winget
  avec confirmation individuelle, dépôt récupéré sans Git).
- **2026-09-23** — Open WebUI migré vers un venv natif dédié (plus de
  Docker), `launch.py` orchestre Jarvis + Open WebUI en un seul script,
  toggle uniforme via `config.yml` (`open_webui.enabled`).
- **2026-09-23** — Chaque module optionnel (`home_assistant`, `weather`,
  `alerts`, `dashboard`, `open_webui`, `update_check`) utilise une clé
  `enabled` uniforme dans `config.yml`. Règle stricte, sans exception :
  clé absente = désactivé, jamais déduit d'un autre réglage (`token`,
  `feed_url`...) — la rétrocompatibilité initialement construite pour
  `home_assistant`/`alerts` (déduction depuis `token`/`feed_url` si
  `enabled` absent) a été retirée sur demande explicite, au profit d'une
  règle simple et identique pour tous les modules.
- **2026-09-23** — Documentation réorganisée : README raccourci, détail
  technique dans `ARCHITECTURE.md`, suivi des fonctionnalités dans ce
  fichier.
