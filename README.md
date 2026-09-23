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
· minuteurs · date/heure · panneau de ressources local.

Chaque module optionnel s'active/désactive avec `enabled: true/false` dans
`config.yml` (voir [`config.yml.example`](config.yml.example)). Détails de
fonctionnement de chaque module : [ARCHITECTURE.md](ARCHITECTURE.md).

## 🚀 Installation (Windows 11)

Prérequis : Python 3.11, GPU NVIDIA (CUDA) recommandé, un micro,
[Ollama](https://ollama.com).

```powershell
winget install --id Git.Git -e
winget install Python.Python.3.11
irm https://ollama.com/install.ps1 | iex
ollama pull qwen2.5:7b
```

```powershell
git clone https://github.com/pazpop/assistant-vocal-local.git
cd assistant-vocal-local
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
Copy-Item config.yml.example config.yml   # adapte au moins ta ville sous location:
cd models\piper
python -m piper.download_voices fr_FR-tom-medium
cd ..\..\server
python main.py
```

Dis **"Hey Jarvis"** pour commencer.

Pas de GPU NVIDIA, voix féminine, configuration de Home Assistant, dépannage
GPU : voir [ARCHITECTURE.md](ARCHITECTURE.md#installation-avancée) et
[Points d'attention](ARCHITECTURE.md#points-dattention).

## 🧩 Stack

openWakeWord (mot-clé) · Silero VAD · faster-whisper (STT, GPU) ·
Ollama/Qwen2.5:7b (LLM) · Piper (TTS, CPU) · Home Assistant (domotique, API
REST locale) · Open-Meteo + Environnement Canada (météo/alertes, gratuits,
sans clé). Schéma complet et choix techniques : [ARCHITECTURE.md](ARCHITECTURE.md).

## 🧪 Tests

```powershell
pip install pytest
pytest tests/
```

Logique pure uniquement (pas le micro/LLM/Piper, à valider manuellement en
lançant `server/main.py`) — voir [tests/README.md](tests/README.md).

## Aller plus loin

- **Architecture** : [ARCHITECTURE.md](ARCHITECTURE.md) — schéma, choix
  techniques, chaque fonctionnalité en détail, points d'attention, limites
  connues
- **Roadmap** : [ROADMAP.md](ROADMAP.md) — fonctionnalités intégrées, à
  venir, et décisions écartées (avec le pourquoi)

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
