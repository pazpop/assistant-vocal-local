"""Texte affiché par le satellite pour montrer où passe le temps entre la fin
de la question et le début de la réponse (enregistrement, encodage, envoi,
transcription, LLM + synthèse).

Fonctions pures (nombres -> texte), sans matériel audio ni réseau : main.py
les appelle au fil de l'échange, les tests les vérifient à part.
"""


def resumer_enregistrement(
    duree_s: float,
    debut_parole_s: float,
    fin_parole_s: float,
    coupe_par_duree_max: bool,
    duree_max_s: float,
    niveau_fond: float,
    seuil: float,
    seuil_min: float,
) -> str:
    """Ventile la durée d'enregistrement : le temps avant de parler, la parole
    elle-même, et le silence attendu avant de conclure que la question est
    finie (c'est la partie que audio.silence_duration permet de raccourcir).
    Indique aussi le bruit de fond mesuré et le seuil de parole qui en découle
    : ce sont eux qui décident où la parole s'arrête."""
    parole_s = max(0.0, fin_parole_s - debut_parole_s)
    silence_s = max(0.0, duree_s - fin_parole_s)
    lignes = [
        f"⏱  Enregistrement : {duree_s:.1f} s",
        f"      {debut_parole_s:.1f} s avant de parler · {parole_s:.1f} s de parole · "
        f"{silence_s:.1f} s de silence attendu avant l'envoi",
        f"      bruit de fond {niveau_fond:.3f} → seuil de parole {seuil:.3f} "
        f"(minimum configuré : {seuil_min:.3f})",
    ]
    if coupe_par_duree_max:
        lignes.append(
            f"      ⚠️  arrêté par la durée max ({duree_max_s:g} s) : la fin de parole n'a "
            "pas été détectée (bruit de fond très variable ? essaie --debug-audio)"
        )
    return "\n".join(lignes)


def formater_etape(etape: str, **infos: float) -> str | None:
    """Ligne à afficher pour une étape de l'échange avec le serveur (voir
    client_api.demander), ou None pour une étape sans affichage.

    Les durées `depuis_envoi` sont mesurées à partir de l'instant où la requête
    part vers le serveur ; `depuis_transcription` à partir de la fin de la
    transcription (le serveur commence à répondre dès qu'elle est faite)."""
    if etape == "wav_cree":
        return (
            f"📦 WAV créé : {infos['duree_audio']:.1f} s d'audio, "
            f"{infos['octets'] / 1024:.0f} Ko (encodage {infos['duree_encodage'] * 1000:.0f} ms)"
        )
    if etape == "envoi":
        return "📤 Envoi au serveur..."
    if etape == "transcription_finie":
        return f"📝 Serveur : transcription terminée (+{infos['depuis_envoi']:.2f} s après l'envoi)"
    if etape == "premiere_phrase":
        return (
            f"🔊 1er audio de réponse reçu : +{infos['depuis_envoi']:.2f} s après l'envoi "
            f"(dont {infos['depuis_transcription']:.2f} s de LLM + synthèse)"
        )
    return None
