"""Génère une clé API aléatoire, pour satellite.api_key dans config.yml
(bibliothèque standard uniquement, aucune dépendance). Ne concerne pas
open_webui.api_key : cette clé-là doit être générée par Open WebUI
lui-même (Réglages > Compte > Clés API), pas choisie ici.

Usage :
    python generate_api_key.py
    python generate_api_key.py --longueur 24
"""
import argparse
import secrets


def main() -> None:
    parser = argparse.ArgumentParser(description="Génère une clé API aléatoire.")
    parser.add_argument(
        "--longueur",
        type=int,
        default=16,
        help="Nombre d'octets aléatoires (défaut 16, soit une clé hexadécimale de 32 caractères).",
    )
    args = parser.parse_args()

    print(secrets.token_hex(args.longueur))


if __name__ == "__main__":
    main()
