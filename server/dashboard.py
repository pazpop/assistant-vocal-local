"""Panneau de ressources local : petit serveur HTTP (bibliothèque standard)
qui affiche l'usage CPU/RAM/VRAM et la latence du pipeline vocal, pour
visualiser rapidement ce que consomme l'assistant.

N'écoute que sur 127.0.0.1 : pensé pour un accès local uniquement, pas pour
être exposé sur le réseau. Volontairement construit avec un simple
http.server (aucune dépendance web ajoutée) : c'est aussi la première brique
d'une future API locale pour les satellites, qu'on étendra plus tard plutôt
que de maintenir un serveur séparé rien que pour ce panneau.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import psutil

try:
    import pynvml

    pynvml.nvmlInit()
    _GPU_HANDLE = pynvml.nvmlDeviceGetHandleByIndex(0)
except Exception:
    # Pas de GPU NVIDIA, pilotes absents, ou pynvml non installé (setup
    # AMD/CPU) : le panneau fonctionne quand même, juste sans section GPU.
    _GPU_HANDLE = None

# Dernières latences mesurées (secondes), mises à jour par main.py au fil de
# la conversation. None tant qu'aucune mesure n'a encore été prise.
_latences: dict[str, float | None] = {"stt": None, "reponse": None}


def enregistrer_latence(etape: str, secondes: float) -> None:
    """Appelé par main.py après chaque étape du pipeline (voir _latences)."""
    _latences[etape] = secondes


def _mesurer_ressources() -> dict:
    ram = psutil.virtual_memory()
    donnees = {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "ram_used_mo": round(ram.used / 1_000_000),
        "ram_total_mo": round(ram.total / 1_000_000),
        "gpu": None,
        "latences": dict(_latences),
    }
    if _GPU_HANDLE is not None:
        try:
            info = pynvml.nvmlDeviceGetMemoryInfo(_GPU_HANDLE)
            donnees["gpu"] = {
                "nom": pynvml.nvmlDeviceGetName(_GPU_HANDLE),
                "vram_used_mo": round(info.used / 1_000_000),
                "vram_total_mo": round(info.total / 1_000_000),
            }
        except Exception:
            pass
    return donnees


_PAGE_HTML = """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="2">
<title>Jarvis - Ressources</title>
<style>
body {{ font-family: sans-serif; background: #111; color: #eee; padding: 2em; }}
h1 {{ font-size: 1.3em; }}
.metrique {{ margin: 0.8em 0; }}
.barre {{ background: #333; border-radius: 4px; height: 14px; width: 300px; overflow: hidden; }}
.remplissage {{ background: #4caf50; height: 100%; }}
</style>
</head>
<body>
<h1>Jarvis - Ressources</h1>
{contenu}
<p style="opacity:0.5; font-size:0.8em;">Rafraîchi toutes les 2 secondes.</p>
</body>
</html>
"""


def _barre(pourcentage: float) -> str:
    pourcentage = max(0.0, min(100.0, pourcentage))
    return f'<div class="barre"><div class="remplissage" style="width:{pourcentage:.0f}%"></div></div>'


def _rendre_html(donnees: dict) -> str:
    pourcentage_ram = 100 * donnees["ram_used_mo"] / donnees["ram_total_mo"]
    lignes = [
        f'<div class="metrique">CPU : {donnees["cpu_percent"]:.0f}% {_barre(donnees["cpu_percent"])}</div>',
        f'<div class="metrique">RAM : {donnees["ram_used_mo"]} / {donnees["ram_total_mo"]} Mo '
        f'{_barre(pourcentage_ram)}</div>',
    ]
    if donnees["gpu"]:
        gpu = donnees["gpu"]
        pourcentage_vram = 100 * gpu["vram_used_mo"] / gpu["vram_total_mo"]
        lignes.append(
            f'<div class="metrique">GPU ({gpu["nom"]}) VRAM : {gpu["vram_used_mo"]} / '
            f'{gpu["vram_total_mo"]} Mo {_barre(pourcentage_vram)}</div>'
        )
    else:
        lignes.append('<div class="metrique">GPU : non détecté (CPU uniquement)</div>')

    stt = donnees["latences"].get("stt")
    reponse = donnees["latences"].get("reponse")
    lignes.append(
        '<div class="metrique">Dernière transcription (STT) : '
        f'{f"{stt:.2f}s" if stt is not None else "—"}</div>'
    )
    lignes.append(
        '<div class="metrique">Dernière réponse complète (LLM + TTS) : '
        f'{f"{reponse:.2f}s" if reponse is not None else "—"}</div>'
    )
    return "\n".join(lignes)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        pass  # Silencieux : sinon chaque rafraîchissement (2s) pollue la console.

    def do_GET(self) -> None:
        donnees = _mesurer_ressources()
        if self.path == "/status":
            corps = json.dumps(donnees).encode("utf-8")
            content_type = "application/json; charset=utf-8"
        else:
            corps = _PAGE_HTML.format(contenu=_rendre_html(donnees)).encode("utf-8")
            content_type = "text/html; charset=utf-8"

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)


def demarrer(port: int) -> str:
    """Lance le panneau dans un thread à part (démon), retourne son URL."""
    serveur = HTTPServer(("127.0.0.1", port), _Handler)
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{port}/"
