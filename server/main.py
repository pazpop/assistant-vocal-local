"""Point d'entrée : boucle principale de l'assistant vocal.

Flux : mot-clé -> enregistrement -> STT -> (reset historique ?) -> LLM
(streaming, + outils domotique Home Assistant si configuré) -> TTS -> lecture.

Le LLM et le TTS tournent en pipeline : dès qu'une phrase complète arrive du
LLM, elle est synthétisée puis mise en file pour lecture, pendant que le LLM
continue de générer la suite.
"""
import argparse
import queue
import random
import re
import threading
import time

import numpy as np

import config
import dashboard
import date_time
from audio_io import play_audio, record_until_silence
from date_time import DATE_TIME_TOOLS, demande_date_heure
from home_assistant import HA_TOOLS, HomeAssistantClient, demande_domotique
from llm import LanguageModel, demande_de_reset
from stt import SpeechToText
from timer import TIMER_TOOLS, TimerManager, demande_minuteur, generer_sonnerie
from trigger import contient_une_phrase
from tts import TextToSpeech
from vad import VoiceActivityDetector
from wakeword import WakeWordDetector
from weather import WEATHER_TOOLS, WeatherClient, demande_meteo
from weather_alerts import ALERT_TOOLS, AlertesMeteoClient, demande_alerte

FIN_DE_PHRASE = re.compile(r"([^.!?]*[.!?]+)")

AU_REVOIR = "À la prochaine !"
INCOMPREHENSION = "Désolé, je n'ai pas compris. Je repasse en veille."


def demande_fin_conversation(texte: str) -> bool:
    """Détecte si une phrase transcrite demande de terminer la conversation
    continue (ex: "Merci Jarvis"), pour repasser en veille (mot-clé)."""
    return contient_une_phrase(texte, config.CONVERSATION_END_PHRASES)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assistant vocal Jarvis")
    parser.add_argument(
        "--debug-audio",
        action="store_true",
        help="Affiche en direct le score du mot-clé et la probabilité de "
        "parole (VAD), pour calibrer wake_word.threshold et audio.vad_threshold "
        "dans config.yml.",
    )
    return parser.parse_args()


def parler_en_flux(fragments_llm, tts: TextToSpeech, file_audio: "queue.Queue") -> None:
    """Consomme le flux du LLM, synthétise phrase par phrase, met en file pour lecture."""
    tampon = ""
    for fragment in fragments_llm:
        print(fragment, end="", flush=True)
        tampon += fragment

        while (trouve := FIN_DE_PHRASE.match(tampon)):
            phrase = trouve.group(1)
            tampon = tampon[len(phrase):]
            phrase = phrase.strip()
            if phrase:
                file_audio.put(tts.synthesize(phrase))

    reste = tampon.strip()
    if reste:
        file_audio.put(tts.synthesize(reste))

    file_audio.put(None)  # sentinelle : plus rien à jouer


def lecteur_audio(file_audio: "queue.Queue", sample_rate: int) -> None:
    """Tourne dans un thread à part : joue les segments audio dès qu'ils arrivent."""
    while True:
        audio = file_audio.get()
        if audio is None:
            break
        play_audio(audio, sample_rate)


def construire_system_prompt(ha_client: HomeAssistantClient | None) -> str:
    """Injecte la liste des appareils Home Assistant dans le prompt système,
    pour que le LLM connaisse les entity_id exacts sans avoir à les deviner."""
    if ha_client is None:
        return config.LLM_SYSTEM_PROMPT_TEMPLATE.format(
            appareils="(Home Assistant non configuré)"
        )

    lignes = []
    for domaine in ("light", "switch"):
        for entite in ha_client.lister_appareils(domaine):
            entity_id = entite["entity_id"]
            nom = config.HA_DEVICE_ALIASES.get(entity_id) or entite["attributes"].get(
                "friendly_name", entity_id
            )
            lignes.append(f"- {entity_id} : {nom}")

    appareils = "\n".join(lignes) if lignes else "(aucun appareil détecté sur Home Assistant)"
    return config.LLM_SYSTEM_PROMPT_TEMPLATE.format(appareils=appareils)


def construire_outils(
    ha_client: HomeAssistantClient | None,
    weather_client: WeatherClient | None,
    timer_manager: TimerManager,
    alertes_client: AlertesMeteoClient | None,
) -> tuple[list[dict], "callable"]:
    """Combine les outils disponibles (domotique + météo + alertes + minuteur
    + date/heure) et construit le dispatcher unique à passer à
    llm.ask_with_tools. Ajouter une future intégration revient à répéter ce
    patron : un client, ses TOOLS, et une entrée ici."""
    tools: list[dict] = list(TIMER_TOOLS) + list(DATE_TIME_TOOLS)
    if ha_client is not None:
        tools += HA_TOOLS
    if weather_client is not None:
        tools += WEATHER_TOOLS
    if alertes_client is not None:
        tools += ALERT_TOOLS

    def executer_outil(nom: str, arguments: dict) -> str:
        if ha_client is not None and nom in {"allumer", "eteindre"}:
            return ha_client.executer_outil(nom, arguments)
        if weather_client is not None and nom == "obtenir_meteo":
            return weather_client.executer_outil(nom, arguments)
        if alertes_client is not None and nom == "obtenir_alerte_meteo":
            return alertes_client.executer_outil(nom, arguments)
        if nom in {"demarrer_minuteur", "lister_minuteurs", "annuler_minuteur"}:
            return timer_manager.executer_outil(nom, arguments)
        if nom == "obtenir_date_heure":
            return date_time.executer_outil(nom, arguments)
        return f"Outil indisponible : {nom}"

    return tools, executer_outil


def main() -> None:
    args = parse_args()

    print("Chargement des modèles (ça peut prendre quelques secondes)...")
    detector = WakeWordDetector()
    stt = SpeechToText()
    tts = TextToSpeech()
    vad = VoiceActivityDetector()

    try:
        ha_client: HomeAssistantClient | None = HomeAssistantClient()
        print("✅ Connecté à Home Assistant.")
    except RuntimeError as exc:
        print(f"⚠️  Domotique désactivée : {exc}")
        ha_client = None

    try:
        weather_client: WeatherClient | None = WeatherClient()
        print(f"✅ Météo activée pour {config.LOCATION_CITY}.")
    except RuntimeError as exc:
        print(f"⚠️  Météo désactivée : {exc}")
        weather_client = None

    def annoncer_alerte(texte: str) -> None:
        """Appelé (dans le thread de sondage de AlertesMeteoClient) dès
        qu'une nouvelle alerte météo apparaît dans le flux — jamais pour une
        alerte déjà annoncée. play_audio() sérialise avec le reste (réponses,
        minuteurs) via le même verrou."""
        message = f"Alerte météo : {texte}"
        print(f"\n🚨 Jarvis  : {message}\n")
        play_audio(tts.synthesize(message), tts.sample_rate)

    try:
        alertes_client: AlertesMeteoClient | None = AlertesMeteoClient(on_nouvelle_alerte=annoncer_alerte)
        print("✅ Alertes météo activées.")
    except RuntimeError as exc:
        print(f"⚠️  Alertes météo désactivées : {exc}")
        alertes_client = None

    # Le minuteur sonne dans son propre thread (threading.Timer), donc
    # potentiellement pendant que Jarvis écoute ou parle déjà autre chose.
    # play_audio() (audio_io.py) sérialise la lecture pour éviter que ça se
    # chevauche avec une réponse en cours.
    sonnerie_audio = generer_sonnerie(tts.sample_rate)

    def annoncer_fin_minuteur(label: str) -> None:
        message = f"Le minuteur {label} est terminé." if label else "Le minuteur est terminé."
        print(f"\n🔔 Jarvis  : {message}\n")
        play_audio(np.concatenate([sonnerie_audio, tts.synthesize(message)]), tts.sample_rate)

    timer_manager = TimerManager(on_expire=annoncer_fin_minuteur)

    tools_disponibles, executer_outil = construire_outils(
        ha_client, weather_client, timer_manager, alertes_client
    )

    if config.DASHBOARD_ENABLED:
        dashboard_url = dashboard.demarrer(config.DASHBOARD_PORT)
        print(f"📊 Panneau de ressources : {dashboard_url}")
    else:
        print("📊 Panneau de ressources désactivé (dashboard.enabled: false).")

    llm = LanguageModel(system_prompt=construire_system_prompt(ha_client))

    # Pré-synthétisées une fois pour toutes : évite de faire tourner Piper
    # (et donc d'ajouter de la latence) à chaque déclenchement du mot-clé ou
    # appel d'outil.
    salutation_audio = tts.synthesize(config.WAKE_WORD_PROMPT)
    tool_call_audios = {
        phrase: tts.synthesize(phrase) for phrase in config.LLM_TOOL_CALL_PHRASES
    }

    print(f"Assistant prêt. Dis '{config.WAKE_WORD_DISPLAY_NAME}' pour commencer.")
    print(
        "(Ctrl+C pour quitter — \"oublie tout\" efface la mémoire — "
        "\"merci Jarvis\" termine la conversation)\n"
    )

    while True:
        try:
            detector.wait_for_wakeword(debug=args.debug_audio)
            print("🎤 Mot-clé détecté, je t'écoute...")

            # L'enregistrement démarre tout de suite, en parallèle de la
            # salutation parlée — pas après. Comme ça, si tu enchaînes ta
            # question directement après "Hey Jarvis" sans attendre "Oui,
            # comment puis-je vous aider ?", elle est quand même captée.
            resultat_ecoute: dict = {}

            def _ecouter_pendant_la_salutation() -> None:
                resultat_ecoute["audio"] = record_until_silence(vad, debug=args.debug_audio)

            thread_ecoute = threading.Thread(target=_ecouter_pendant_la_salutation, daemon=True)
            thread_ecoute.start()

            print(f"Jarvis  : {config.WAKE_WORD_PROMPT}")
            play_audio(salutation_audio, tts.sample_rate)

            thread_ecoute.join()
            audio = resultat_ecoute["audio"]

            # Conversation continue : tant qu'on obtient une question valide,
            # on réécoute directement après la réponse, sans redemander le
            # mot-clé. On sort de cette boucle (retour en veille) si
            # personne ne parle dans le délai imparti, si le STT ne comprend
            # rien, ou sur "merci Jarvis".
            while True:
                if audio.size == 0:
                    print("→ Aucun audio capté, retour en veille.\n")
                    break

                t0 = time.time()
                question = stt.transcribe(audio)
                dt_stt = time.time() - t0
                if question and contient_une_phrase(question, ("abracadabra",)):
                    # Easter egg : déclenche volontairement le comportement
                    # "incompréhension" ci-dessous, pratique pour le tester
                    # sans avoir à réellement marmonner dans le micro.
                    question = ""
                if not question:
                    print(f"Jarvis  : {INCOMPREHENSION}\n")
                    play_audio(tts.synthesize(INCOMPREHENSION), tts.sample_rate)
                    break
                dashboard.enregistrer_latence("stt", dt_stt)
                print(f"Toi     : {question}  (STT: {dt_stt:.2f}s)")

                if demande_de_reset(question):
                    llm.reset_history()
                    print(f"Jarvis  : {config.MEMORY_RESET_CONFIRMATION}\n")
                    play_audio(tts.synthesize(config.MEMORY_RESET_CONFIRMATION), tts.sample_rate)
                    audio = record_until_silence(
                        vad, debug=args.debug_audio, no_speech_timeout=config.CONVERSATION_FOLLOWUP_TIMEOUT
                    )
                    continue

                if demande_fin_conversation(question):
                    print(f"Jarvis  : {AU_REVOIR}\n")
                    play_audio(tts.synthesize(AU_REVOIR), tts.sample_rate)
                    break

                file_audio: "queue.Queue" = queue.Queue()
                thread_lecture = threading.Thread(
                    target=lecteur_audio, args=(file_audio, tts.sample_rate), daemon=True
                )
                thread_lecture.start()

                def on_tool_call() -> None:
                    """Appelé dès que le LLM décide d'utiliser un outil (météo,
                    minuteur, domotique) : met une phrase en file tout de suite,
                    jouée par thread_lecture en parallèle de l'appel réseau qui
                    suit — jamais déclenché pour une réponse conversationnelle."""
                    phrase = random.choice(config.LLM_TOOL_CALL_PHRASES)
                    file_audio.put(tool_call_audios[phrase])

                t_reponse = time.time()
                print("Jarvis  : ", end="", flush=True)
                if alertes_client is not None and demande_alerte(question):
                    # Vérifié AVANT la météo : "alerte météo" contient le mot
                    # "météo", qui déclencherait sinon la branche météo à la
                    # place (WEATHER_TRIGGER_PHRASES matche sur "météo" seul).
                    fragments = llm.ask_tool_direct(
                        question,
                        tools=ALERT_TOOLS,
                        tool_executor=alertes_client.executer_outil,
                        on_tool_call=on_tool_call,
                    )
                elif weather_client is not None and demande_meteo(question):
                    # ask_tool_direct (pas ask_with_tools) : l'outil renvoie
                    # déjà une phrase complète prête à être dite, donc on la
                    # relaie telle quelle plutôt que de la faire reformuler
                    # par le LLM (source de gabarits non remplis/de dérives
                    # en anglais). Sans historique non plus : le LLM reste
                    # libre d'extraire une ville explicitement nommée (ex:
                    # "quel temps fait-il à Paris ?") sans répondre de mémoire.
                    fragments = llm.ask_tool_direct(
                        question,
                        tools=WEATHER_TOOLS,
                        tool_executor=weather_client.executer_outil,
                        on_tool_call=on_tool_call,
                    )
                elif demande_date_heure(question):
                    # Même raison que pour la météo juste au-dessus.
                    fragments = llm.ask_tool_direct(
                        question,
                        tools=DATE_TIME_TOOLS,
                        tool_executor=date_time.executer_outil,
                        on_tool_call=on_tool_call,
                    )
                elif demande_minuteur(question):
                    # Même raison que pour la météo/date-heure : sans ça, dès
                    # qu'un minuteur a déjà été démarré dans la conversation,
                    # le LLM saute parfois l'appel à l'outil et invente une
                    # fausse confirmation de succès (minuteur jamais démarré).
                    fragments = llm.ask_tool_direct(
                        question,
                        tools=TIMER_TOOLS,
                        tool_executor=timer_manager.executer_outil,
                        on_tool_call=on_tool_call,
                    )
                elif ha_client is not None and (action_ha := demande_domotique(question)) is not None:
                    # Même raison que météo/date-heure/minuteur : constaté en
                    # pratique, ex. "allume la cuisine" puis "éteins la
                    # cuisine" dans la foulée — le LLM confirme l'extinction
                    # sans jamais rappeler l'outil, la lumière reste allumée.
                    fragments = llm.ask_tool_direct(
                        question,
                        tools=[outil for outil in HA_TOOLS if outil["function"]["name"] == action_ha],
                        tool_executor=ha_client.executer_outil,
                        on_tool_call=on_tool_call,
                    )
                elif tools_disponibles:
                    fragments = llm.ask_with_tools(
                        question,
                        tools=tools_disponibles,
                        tool_executor=executer_outil,
                        on_tool_call=on_tool_call,
                    )
                else:
                    fragments = llm.ask_stream(question)
                parler_en_flux(fragments, tts, file_audio)
                print()

                thread_lecture.join()
                dashboard.enregistrer_latence("reponse", time.time() - t_reponse)
                print("👂 (je t'écoute encore — dis \"merci Jarvis\" pour terminer)\n")

                audio = record_until_silence(
                    vad, debug=args.debug_audio, no_speech_timeout=config.CONVERSATION_FOLLOWUP_TIMEOUT
                )

        except KeyboardInterrupt:
            print("\nArrêt de l'assistant.")
            break
        except Exception as exc:  # noqa: BLE001 - on veut survivre à une erreur ponctuelle
            print(f"[erreur] {exc!r} — je continue à écouter.\n")


if __name__ == "__main__":
    main()
