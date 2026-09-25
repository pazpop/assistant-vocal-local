![Jarvis — assistant vocal 100% local](assets/banner.svg)

# 🎙️ Jarvis maison — assistant vocal local (STT → LLM → TTS)

Assistant vocal francophone qui tourne **entièrement en local** : mot-clé,
reconnaissance vocale, LLM (Ollama), synthèse vocale, et domotique via Home
Assistant — sans dépendre d'un service cloud tiers.

> Conçu par [pazpop](https://github.com/pazpop), en collaboration avec
> [Claude](https://claude.com) (Anthropic) et [Lumo](https://lumo.proton.me)
> (Proton) — voir
> [Crédits](#-crédits--licence).

## 🎓 Pourquoi ce projet ?

Je ne suis pas développeur de métier — un **POC** pour comprendre comment
s'assemble un assistant vocal (mot-clé, VAD, STT, LLM, TTS) en restant 100%
local, avec l'aide de Claude et Lumo. J'espère un jour
faire évoluer ça jusqu'à remplacer mes HomePod mini. Mes choix sont
probablement discutables par endroits — je reste ouvert à toute
amélioration.

## ✨ Fonctionnalités

Mot-clé "Hey Jarvis" · conversation continue · transcription GPU
(faster-whisper) · LLM local (Ollama) · synthèse vocale (Piper) · domotique
(Home Assistant) · météo + alertes météo (Open-Meteo, Environnement Canada)
· minuteurs · date/heure · panneau de ressources local · interface web de
conversation façon ChatGPT (Open WebUI, optionnelle).

Chaque module optionnel s'active/désactive avec `enabled: true/false` dans
`config.yml` (voir [`config.yml.example`](config.yml.example)). Détails de
fonctionnement de chaque module : [ARCHITECTURE.md](ARCHITECTURE.md).

## 🚀 Installation (Windows 11)

Prérequis : rien — ouvre PowerShell et lance :

```powershell
irm https://raw.githubusercontent.com/pazpop/assistant-vocal-local/main/install.ps1 | iex
```

Installe Python et Ollama si besoin (**confirmation demandée pour chacun**,
rien ne s'installe à ton insu), récupère le dépôt, crée le venv, installe
les dépendances, télécharge le modèle Ollama (`qwen2.5:7b`, ~4,7 Go) et la
voix Piper. Ne lance rien à la fin — il affiche la commande pour démarrer
Jarvis toi-même. Détail du script : [ARCHITECTURE.md](ARCHITECTURE.md#installation).

```powershell
cd assistant-vocal-local
.\.venv\Scripts\python.exe launch.py
```

Dis **"Hey Jarvis"** pour commencer. `launch.py` démarre Jarvis (et Open WebUI
si activé dans `config.yml` — voir [ARCHITECTURE.md](ARCHITECTURE.md#open-webui)) ;
Ctrl+C arrête tout proprement.

**Dépôt déjà sur ton disque ?** Double-clique sur `install.bat` (les `.ps1`
ne sont jamais exécutables au double-clic sous Windows). En secours : clic
droit sur `install.ps1` → **Exécuter avec PowerShell**.

**Étapes manuelles**, si tu préfères tout faire toi-même :

```powershell
winget install Python.Python.3.11
winget install --id Ollama.Ollama -e
winget install --id Git.Git -e
git clone https://github.com/pazpop/assistant-vocal-local.git
cd assistant-vocal-local
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
Copy-Item config.yml.example config.yml   # adapte au moins ta ville sous location:
ollama pull qwen2.5:7b
cd models\piper
python -m piper.download_voices fr_FR-tom-medium
cd ..\..
python launch.py
```

Pas de GPU NVIDIA, voix féminine, configuration de Home Assistant, dépannage
GPU : voir [ARCHITECTURE.md](ARCHITECTURE.md#installation-avancée) et
[Points d'attention](ARCHITECTURE.md#points-dattention).

## 🧪 Tests

```powershell
pip install pytest
pytest tests/
```

Pas de micro/LLM/Piper (à valider en lançant `server/main.py`) — voir
[tests/README.md](tests/README.md). Stack et choix techniques :
[ARCHITECTURE.md](ARCHITECTURE.md).

## Aller plus loin

- **Architecture** : [ARCHITECTURE.md](ARCHITECTURE.md) — schéma, choix
  techniques, chaque fonctionnalité en détail, points d'attention, limites
  connues
- **Roadmap** : [ROADMAP.md](ROADMAP.md) — ce qui reste à faire

## 🙏 Crédits & licence

Conçu par **[pazpop](https://github.com/pazpop)** aidé par **Claude**
(Anthropic) et **Lumo** (Proton).

Inspiré en partie de
[sosoj92/jarvis-assistant-vocal](https://github.com/sosoj92/jarvis-assistant-vocal)
(streaming LLM→TTS, minuteur en `threading.Timer`, météo enrichie du vent) et
de [Lex-au/Vocalis](https://github.com/Lex-au/Vocalis) pour la détection de
fin de question par VAD (`server/vad.py`), réimplémentée avec le modèle
Silero déjà embarqué dans `faster-whisper`.

Licence [GPL-3.0](LICENSE) — les dépendances tierces (Piper, faster-whisper,
Ollama...) conservent leurs propres licences respectives.
