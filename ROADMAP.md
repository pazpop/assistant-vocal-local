# Roadmap

Prochaines étapes. Détail technique de l'existant : [ARCHITECTURE.md](ARCHITECTURE.md).

## À venir

### Interface web de conversation (Open WebUI)

- [x] Migré vers un venv Python dédié (`openwebui/.venv-openwebui/`, 2026-09-23) plutôt que Docker — évite d'imposer Docker Desktop pour un seul conteneur. Conflit vérifié qui empêche de le mettre dans le même venv que Jarvis : Open WebUI épingle `onnxruntime==1.26.0`, Jarvis épingle `onnxruntime==1.30.0` (utilisé par `openwakeword`/`vad.py`).
- [x] Base de données (comptes, historique de chat) redirigée hors du venv via `DATA_DIR` (par défaut, Open WebUI l'écrit dans `site-packages/`, perdue si le venv est recréé).
- [x] `qwen2.5-coder` qui recrachait des appels d'outils bruts au lieu de coder (2026-09-23) — **diagnostic initial faux, corrigé après vérification dans le code source d'Open WebUI** : ce n'était pas un system prompt contaminé, mais les "Builtin Tools" (tâches, mémoire, recherche web...) d'Open WebUI, injectés à tous les modèles par défaut (`model.info.meta.capabilities.builtin_tools`, `True` par défaut). Correctif : modèle personnalisé (**Espace de travail > Modèles**) avec **Capacités > Outils intégrés** décoché. Confirmé par l'utilisateur : génère du code Python propre, plus d'appel d'outil halluciné. Manuel, dans l'interface — rien à automatiser côté dépôt.
- **Bug connu en amont (pas le nôtre)** : `KeyError: 'model'` dans les logs d'Open WebUI (`background_tasks_handler`, appelé par `run_initial_title_generation`) — `main.py` construit un dict `title_ctx` sans clé `'model'` alors que `background_tasks_handler` s'attend à la trouver. Non fatal (capté par un `try/except`, casse juste la génération auto du titre de conversation pour ce message). Confirmé toujours présent en 0.11.4 (dernière version au moment de vérifier) — rien à faire de notre côté, pas de correctif à appliquer sur du code tiers.

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

- [x] Job GitHub Actions sur `ubuntu-latest` (`.github/workflows/tests.yml`) : `pip install -r requirements.txt` (lignes CUDA retirées) + `pytest tests/`. Valide que le code Python tourne sur Linux, sans Docker ni build d'image. Objectif aussi : moins besoin de relancer manuellement toute la suite après chaque petite modification. Confirmé fonctionnel sur un vrai push (mis à jour vers `actions/checkout@v7`/`actions/setup-python@v7` après un avertissement de dépréciation Node 20 sur les premières versions testées).
- **Limite à documenter, pas à découvrir plus tard** : les runners gratuits GitHub n'ont pas de GPU — cette CI ne validera jamais le vrai chemin `stt.device: cuda`, seulement le fallback CPU.
- [ ] Tests pour `launch.py` — aujourd'hui zéro couverture automatisée, seulement testé à la main. Les parties qui touchent réseau/sous-process sont difficiles à tester tel quel, mais la logique pure (parsing des arguments, décision "les deux flags de purge en même temps", lecture/validation de `VERSION`) est testable sans lancer Jarvis ou Ollama.

### Satellites Raspberry Pi

Matériel commandé (2026-09-23) : Raspberry Pi 4 Model B/2GB + ReSpeaker
2-Mics Pi HAT v2.0 — `satellite/` accueille le client léger (mot-clé + micro
+ haut-parleur), en attente de matériel pour être testé pour de vrai.
Procédure d'installation du matériel/OS/pilotes (Raspberry Pi Imager, HAT
ReSpeaker) :
[satellite/RASPBERRY_PI_SETUP.md](satellite/RASPBERRY_PI_SETUP.md).

- [x] Serveur API (FastAPI, `server/satellite_api.py`, 2026-09-23) :
  endpoint unique `POST /assistant` (WAV in, WAV out), protégé par une clé
  API (`satellite.api_key`, obligatoire — écoute sur `0.0.0.0` par défaut,
  pas seulement `127.0.0.1`). Réutilise le même `LanguageModel`/routage
  d'outils que la boucle micro locale (`choisir_reponse`, extrait de
  `main.py`) — mêmes outils, même historique de conversation. Détail :
  [ARCHITECTURE.md](ARCHITECTURE.md#api-satellite). Testé de bout en bout
  (démarrage, rejet 401 sans clé valide, réponse WAV 200 avec la bonne clé,
  suite pytest complète toujours au vert) — pas encore avec un vrai
  satellite, qui n'existe pas encore physiquement.
- [x] Client satellite minimal pour Raspberry Pi (`satellite/`, 2026-09-23) :
  mot-clé (openWakeWord) + enregistrement (seuil RMS, pas de VAD Silero —
  voir [ARCHITECTURE.md](ARCHITECTURE.md#client-satellite) pour le
  pourquoi) + envoi HTTP au serveur + lecture de la réponse. Aucun code
  dupliqué depuis `server/` (installation autonome, son propre venv). Un
  tour par mot-clé pour cette première version — pas encore de conversation
  continue côté client (le serveur garde déjà l'historique, donc ça
  viendrait surtout du client). Testé : imports propres, suite pytest dédiée
  (`satellite/tests/`) au vert — pas encore sur un vrai Pi, qui n'est pas
  encore arrivé.
- [ ] Conversation continue côté satellite (réécouter après une réponse sans
  redire "Hey Jarvis", comme la boucle micro locale)
- [ ] Chiffrer le trafic satellite ↔ serveur (TLS) : aujourd'hui en clair
  (HTTP), y compris la clé API elle-même — lisible par quiconque peut
  sniffer le Wi-Fi local. Cohérent avec le reste du projet (Home Assistant,
  Open WebUI tournent aussi en HTTP sur l'hypothèse "réseau local de
  confiance"), mais c'est la première fois que de l'audio vocal traverse
  vraiment le Wi-Fi plutôt que rester sur `127.0.0.1`. Impact perf attendu
  négligeable (le pipeline STT→LLM→TTS prend déjà 1-3+ secondes ; le coût
  TLS se limite à quelques ms, surtout si la connexion HTTP est réutilisée
  plutôt que rouverte à chaque question). Le vrai coût sera la complexité
  (certificat auto-signé à générer/distribuer, `verify_ssl` côté client
  comme pour Home Assistant), pas la latence.
- [x] Démarrage automatique du client au boot du Pi (service systemd,
  2026-09-23) : documenté dans
  [satellite/README.md](satellite/README.md#démarrage-automatique-systemd) —
  unité générée par un bloc de commandes (`$USER`/`$(pwd)` substitués par le
  shell), `Restart=on-failure` en filet de sécurité en plus de la boucle
  `try/except` déjà présente dans `main.py`. Pas encore testé sur un vrai Pi.
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

- [ ] Réintégrer ComfyUI (launcher Windows ou Docker isolé — ce projet-ci n'utilise pas Docker, mais ComfyUI n'a aucune interaction avec le reste de la stack, donc reste indépendant de ce choix) + SDXL + LoRA Lightning
- [ ] Intégration Open WebUI (**Paramètres > Images > ComfyUI Base URL**)
- **Attention** : VRAM (6-8 Go) potentiellement incompatible avec Jarvis actif sur la RTX 3080 (10 Go) — cohabitation à valider avant d'aller plus loin.

### Mise à jour du projet

- [ ] Documenter comment mettre à jour une installation existante.
  `install.ps1` ne sait aujourd'hui que faire une installation neuve — s'il
  détecte que `requirements.txt` est déjà là, il n'essaie pas de retélécharger
  le code. `launch.py` prévient juste qu'une nouvelle version existe
  (`update_check`), sans expliquer quoi faire ensuite.
- [x] `VERSION` automatisé (2026-09-23) : job `bump-version` dans
  `.github/workflows/tests.yml`, format `MAJOR.commits` (`1.19`
  actuellement) sur le modèle d'arcadepipe — `MAJOR` fixé à la main dans le
  workflow (vraie release), le nombre de commits (`git rev-list --count HEAD`)
  recalculé automatiquement à chaque push. Se déclenche après les tests,
  sur push vers `main` seulement, commit le résultat avec `[skip ci]` pour
  ne pas se redéclencher. Le calcul reste côté CI (qui a Git) — `install.ps1`
  ne dépend toujours pas de Git côté utilisateur. Confirmé fonctionnel sur
  un vrai push, commit automatique inclus.
