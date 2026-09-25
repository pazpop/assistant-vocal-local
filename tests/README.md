# Tests

Lance les tests avec :
```
pip install -r requirements.txt pytest
pytest tests/
```

Logique pure (routage, outils, minuteurs, flux de phrases, API satellite via
TestClient) et VAD réel (modèle ONNX local) — pas le micro, le LLM ni Piper,
à valider manuellement. Les tests du client (`satellite/tests/`) se lancent
séparément : `pytest satellite/tests/` (voir satellite/README.md).
