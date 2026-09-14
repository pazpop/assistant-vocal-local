# models/

Ce dossier contient les poids des modèles téléchargés localement. Il n'est
**pas versionné** (voir `.gitignore`) — ces fichiers sont gros et se
retéléchargent facilement.

- `piper/` — voix Piper (`.onnx` + `.onnx.json`), via
  `python -m piper.download_voices fr_FR-tom-medium`
- `whisper/` — cache des modèles faster-whisper (rempli automatiquement au
  premier lancement)
- `openwakeword/` — modèles de détection du mot-clé (rempli automatiquement
  au premier lancement)
