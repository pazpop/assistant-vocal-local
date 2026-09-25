# Roadmap

Ce qui reste à faire. L'existant (et le pourquoi des choix) est dans
[ARCHITECTURE.md](ARCHITECTURE.md) ; l'historique, dans git.

## Prioritaire

### Météo : prévisions

- [ ] Répondre à « Quelle est la météo pour demain ? » (et après-demain, ce
  week-end...) : `weather.py` ne donne que la météo actuelle. Open-Meteo
  fournit déjà les prévisions journalières (`daily`), sans clé. Ajouter un
  paramètre de jour à l'outil `obtenir_meteo`, résumer en une phrase parlée
  (conditions, min/max, pluie), et tester le déclencheur (« demain » ne doit
  pas tomber sur la route date/heure).

### Suites de la revue du 2026-09-25

- [ ] Tests pour le reste de `launch.py` (seule la version est couverte) : arguments, refus
  des deux purges combinées, lecture de la version.
- [ ] Alertes météo : les diffuser aussi aux satellites (aujourd'hui, seul le
  PC les annonce). Même mécanisme que les minuteurs (`BoiteNotifications`).
- [ ] Sécurité : une clé API par satellite ; limiter les essais de clé.
- [ ] Mesurer `beam_size=1` pour le STT (latence).
- [ ] Routage par sous-chaîne (`trigger.py`) : normaliser accents/apostrophes
  une fois, plutôt que lister les variantes à la main.
- [ ] `docs` : raccourcir les doublons (purges Open WebUI, `install.ps1`)
  entre README, ARCHITECTURE et `config.yml.example`.

## Satellites Raspberry Pi

Procédure matériel/OS/pilotes :
[satellite/RASPBERRY_PI_SETUP.md](satellite/RASPBERRY_PI_SETUP.md).

- [ ] Conversation continue côté satellite (réécouter après une réponse sans
  redire « Hey Jarvis »).
- [ ] Vrai VAD sur le Pi (`pysilero-vad`, à vérifier sans PyTorch en Python
  3.13 aarch64) à la place du seuil de volume adaptatif.
- [ ] Annulation d'écho / interruption pendant que Jarvis parle.
- [ ] Chiffrer le trafic satellite ↔ serveur : aujourd'hui HTTP en clair, clé
  API et audio compris. Piste simple : WireGuard/Tailscale entre le Pi et le
  PC, ou un proxy TLS ; sinon certificat auto-signé + `verify_ssl` côté client.
- [ ] Découverte automatique du serveur (mDNS).

## Installation

- [ ] `install.ps1` demande la ville et renseigne `location:` dans
  `config.yml`. Ne demander que la ville (pas « ville + province », propre au
  Canada) : le géocodage Open-Meteo résout `geocode_query`/`timezone`.
- [ ] Documenter la mise à jour d'une installation existante : `install.ps1`
  ne met pas le code à jour, et `launch.py` signale seulement qu'une nouvelle
  version existe.

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
