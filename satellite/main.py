"""Point d'entrée du client satellite : mot-clé -> enregistrement -> envoi au
serveur -> lecture de la réponse.

Version minimale (voir ROADMAP.md > Satellites Raspberry Pi) : un tour par
mot-clé, pas de conversation continue ni de domotique/météo/minuteur en
local — tout le traitement (STT, LLM, outils, TTS) reste sur le serveur, via
server/satellite_api.py. Ce client ne fait qu'enregistrer, transmettre et
jouer la réponse.
"""
import argparse
import sys

import requests

import chrono
import client_api
import config
from audio_io import generer_bip, play_audio, record_until_silence
from wakeword import WakeWordDetector


def afficher_etape(etape: str, **infos: float) -> None:
    """Affiche, au fil de l'échange, chaque étape avec son temps (voir
    chrono.formater_etape) : pour voir ce qui est long entre la fin de la
    question et le début de la réponse."""
    ligne = chrono.formater_etape(etape, **infos)
    if ligne:
        print(ligne, flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Client satellite Jarvis")
    parser.add_argument(
        "--debug-audio",
        action="store_true",
        help="Affiche en direct le score du mot-clé et le niveau audio, pour "
        "calibrer wake_word.threshold et audio.silence_threshold dans config.yml.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not config.SERVER_URL:
        print("❌ server.url manquant dans config.yml — adresse de l'API satellite introuvable.")
        sys.exit(1)
    if not config.SERVER_API_KEY:
        print(
            "❌ server.api_key manquant dans config.yml — même valeur que "
            "satellite.api_key côté serveur (voir generate_api_key.py)."
        )
        sys.exit(1)

    print("Chargement du modèle de mot-clé (ça peut prendre quelques secondes)...")
    detector = WakeWordDetector()
    bip = generer_bip(config.SAMPLE_RATE)

    zone = f" ({config.ZONE_NAME})" if config.ZONE_NAME else ""
    print(f"Satellite prêt{zone}. Dis '{config.WAKE_WORD_DISPLAY_NAME}' pour commencer.")
    print("(Ctrl+C pour quitter)\n")

    while True:
        try:
            detector.wait_for_wakeword(debug=args.debug_audio)
            print("🎤 Mot-clé détecté, je t'écoute...")
            play_audio(bip, config.SAMPLE_RATE)

            enregistrement = record_until_silence(debug=args.debug_audio)
            if enregistrement.audio.size == 0:
                print(
                    f"→ Aucun audio capté ({enregistrement.duree_s:.1f} s d'écoute), "
                    "retour en veille.\n"
                )
                continue

            print(
                chrono.resumer_enregistrement(
                    duree_s=enregistrement.duree_s,
                    debut_parole_s=enregistrement.debut_parole_s,
                    fin_parole_s=enregistrement.fin_parole_s,
                    coupe_par_duree_max=enregistrement.coupe_par_duree_max,
                    duree_max_s=config.MAX_RECORD_SECONDS,
                )
            )

            nb_phrases = 0
            duree_lue = 0.0
            try:
                # Chaque phrase est jouée dès qu'elle arrive, pendant que le
                # serveur prépare la suivante (elle attend dans le tampon réseau
                # pendant que la précédente joue : pas de trou entre deux).
                for phrase_audio, sample_rate in client_api.demander(
                    enregistrement.audio, signaler=afficher_etape
                ):
                    play_audio(phrase_audio, sample_rate)
                    nb_phrases += 1
                    duree_lue += phrase_audio.size / sample_rate
            except requests.RequestException as exc:
                print(f"⚠️  Échange avec le serveur interrompu : {exc}\n")
                continue

            print(f"🔈 Réponse jouée : {nb_phrases} phrase(s), {duree_lue:.1f} s d'audio")
            print("En veille.\n")

        except KeyboardInterrupt:
            print("\nArrêt du satellite.")
            break
        except Exception as exc:  # noqa: BLE001 - on veut survivre à une erreur ponctuelle
            print(f"[erreur] {exc!r} — je continue à écouter.\n")


if __name__ == "__main__":
    main()
