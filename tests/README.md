# Tests

Lance les tests avec :
```
pip install pytest
pytest tests/
```

Ces tests ciblent la logique pure (regex, dispatch d'outils) — pas le micro,
le LLM ni Piper, qui nécessitent du matériel/des services externes et sont
plutôt à valider manuellement (voir README principal).
