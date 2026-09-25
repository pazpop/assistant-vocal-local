"""Point d'entrée : boucle principale de l'assistant vocal.

Flux : mot-clé -> enregistrement -> STT -> (reset historique ?) -> LLM
(streaming, + outils : domotique, météo, minuteur...) -> TTS -> lecture.

Le LLM et le TTS tournent en pipeline : dès qu'une phrase complète arrive du
LLM, elle est synthétisée puis mise en file pour lecture, pendant que le LLM
continue de générer la suite.
"""
import argparse
import functools
import queue
import random
import re
import sys
import threading
import time
from typing import Callable, Iterable, Iterator

import numpy as np

# Robuste face aux emojis (✅/⚠️/⏸️) et accents même quand la console ne
# détecte pas UTF-8 (ex: cp1252, typiquement quand ce script est lancé comme
# sous-process par launch.py plutôt que directement dans un terminal
# interactif) — sans ça, le premier print() avec emoji fait planter Jarvis.
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

import config
import dashboard
import date_time
import satellite_api
from audio_io import play_audio, record_until_silence
from date_time import DATE_TIME_TOOLS, demande_date_heure
from home_assistant import HA_TOOLS, HomeAssistantClient, demande_domotique
from llm import LanguageModel, demande_de_reset
from phrases import decouper_en_phrases
from stt import SpeechToText
from timer import TIMER_TOOLS, TimerManager, demande_minuteur, generer_sonnerie
from trigger import contient_une_phrase
from tts import TextToSpeech
from vad import VoiceActivityDetector
from wakeword import WakeWordDetector
from weather import WEATHER_TOOLS, WeatherClient, outils_meteo
from weather_alerts import ALERT_TOOLS, AlertesMeteoClient, demande_alerte

AU_REVOIR = "À la prochaine !"
INCOMPREHENSION = "Désolé, je n'ai pas compris. Je repasse en veille."
ERREUR_VOCALE = "Désolé, j'ai rencontré un problème. Réessaie dans un instant."
PAUSE_APRES_ERREUR_S = 2  # évite de tourner à 100 % CPU si l'erreur persiste (micro débranché...)


MOTS_MAX_AUTOUR_DE_LA_FIN = 3  # « ok merci Jarvis, bonne soirée » = fin ; plus long = une vraie question


def demande_fin_conversation(texte: str) -> bool:
    """Vrai si la phrase transcrite termine la conversation continue
    (« merci Jarvis »), pour repasser en veille. Seulement si elle se limite
    à cette formule (au plus MOTS_MAX_AUTOUR_DE_LA_FIN autres mots) :
    « merci Jarvis, quelle heure est-il ? » est une question, pas un au revoir."""
    minuscules = texte.lower()
    for phrase in config.CONVERSATION_END_PHRASES:
        if phrase in minuscules:
            reste = minuscules.replace(phrase, " ")
            return len(re.findall(r"\w+", reste)) <= MOTS_MAX_AUTOUR_DE_LA_FIN
    return False


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

    def afficher_au_fil_de_l_eau(fragments):
        for fragment in fragments:
            print(fragment, end="", flush=True)
            yield fragment

    try:
        for phrase in decouper_en_phrases(afficher_au_fil_de_l_eau(fragments_llm)):
            file_audio.put(tts.synthesize(phrase))
    finally:
        file_audio.put(None)  # sentinelle : plus rien à jouer, même après une erreur


def sous_verrou(verrou: threading.Lock, flux: Iterable[str]) -> Iterator[str]:
    """Garde `verrou` pendant tout le flux (et le libère même s'il est
    abandonné en route) : un seul tour de conversation à la fois, pour que
    deux appareils ne mélangent pas l'historique du LLM."""
    with verrou:
        yield from flux


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


def construire_routes_directes(
    ha_client: HomeAssistantClient | None,
    weather_client: WeatherClient | None,
    timer_manager: TimerManager,
    alertes_client: AlertesMeteoClient | None,
    origine: str | None = None,
) -> list[tuple[Callable[[str], list[dict] | None], Callable[[str, dict], str]]]:
    """Construit, dans l'ordre de priorité, les routes vers llm.ask_tool_direct
    (réponse déterministe pour un outil dont le résultat est déjà une phrase
    prête à être dite — voir llm.ask_tool_direct). Chaque route est un couple
    (matcher, tool_executor) où matcher(question) renvoie les outils à
    utiliser si la question correspond, sinon None.

    L'ordre compte : les alertes météo doivent être vérifiées avant la météo,
    car "alerte météo" contient le mot "météo", qui matcherait sinon en
    premier. Ajouter une future intégration revient à ajouter une entrée ici,
    dans construire_outils, et son propre `demande_X` dans son module.

    `origine` : zone du satellite qui parle (None = ce PC), pour que ses
    minuteurs sonnent chez lui."""

    def route_alerte(question: str) -> list[dict] | None:
        return ALERT_TOOLS if demande_alerte(question) else None

    def route_meteo(question: str) -> list[dict] | None:
        return outils_meteo(question)

    def route_date_heure(question: str) -> list[dict] | None:
        return DATE_TIME_TOOLS if demande_date_heure(question) else None

    def route_minuteur(question: str) -> list[dict] | None:
        return TIMER_TOOLS if demande_minuteur(question) else None

    def route_domotique(question: str) -> list[dict] | None:
        action = demande_domotique(question)
        if action is None:
            return None
        return [outil for outil in HA_TOOLS if outil["function"]["name"] == action]

    routes: list[tuple[Callable[[str], list[dict] | None], Callable[[str, dict], str]]] = []
    if alertes_client is not None:
        routes.append((route_alerte, alertes_client.executer_outil))
    if weather_client is not None:
        routes.append((route_meteo, weather_client.executer_outil))
    routes.append((route_date_heure, date_time.executer_outil))
    routes.append((route_minuteur, functools.partial(timer_manager.executer_outil, origine=origine)))
    if ha_client is not None:
        routes.append((route_domotique, ha_client.executer_outil))
    return routes


def construire_outils(
    ha_client: HomeAssistantClient | None,
    weather_client: WeatherClient | None,
    timer_manager: TimerManager,
    alertes_client: AlertesMeteoClient | None,
    origine: str | None = None,
) -> tuple[list[dict], Callable[[str, dict], str]]:
    """Combine les outils disponibles (domotique + météo + alertes + minuteur
    + date/heure) et construit le dispatcher unique à passer à
    llm.ask_with_tools. Le dispatch est dérivé directement des noms d'outils
    déclarés dans chaque TOOLS (au lieu de les relister ici à la main) :
    ajouter une future intégration revient à ajouter une entrée dans
    `sources`, rien d'autre."""
    sources: list[tuple[list[dict], Callable[[str, dict], str]]] = [
        (list(TIMER_TOOLS), functools.partial(timer_manager.executer_outil, origine=origine)),
        (list(DATE_TIME_TOOLS), date_time.executer_outil),
    ]
    if ha_client is not None:
        sources.append((HA_TOOLS, ha_client.executer_outil))
    if weather_client is not None:
        sources.append((WEATHER_TOOLS, weather_client.executer_outil))
    if alertes_client is not None:
        sources.append((ALERT_TOOLS, alertes_client.executer_outil))

    tools: list[dict] = [outil for liste, _ in sources for outil in liste]

    noms = [outil["function"]["name"] for outil in tools]
    doublons = {nom for nom in noms if noms.count(nom) > 1}
    if doublons:
        raise ValueError(f"Noms d'outils en collision entre modules : {doublons}")

    dispatch = {
        outil["function"]["name"]: executeur
        for liste, executeur in sources
        for outil in liste
    }

    def executer_outil(nom: str, arguments: dict) -> str:
        executeur = dispatch.get(nom)
        return executeur(nom, arguments) if executeur else f"Outil indisponible : {nom}"

    return tools, executer_outil


def choisir_reponse(
    question: str,
    llm: LanguageModel,
    routes_directes: list[tuple[Callable[[str], list[dict] | None], Callable[[str, dict], str]]],
    tools_disponibles: list[dict],
    executer_outil: Callable[[str, dict], str],
    on_tool_call: Callable[[], None] | None = None,
) -> Iterator[str]:
    """Route une question vers ask_tool_direct (routes directes prioritaires,
    voir construire_routes_directes) ou ask_with_tools en repli.

    Partagée entre la boucle micro locale et satellite_api.py, pour que les
    deux parlent au même Jarvis (mêmes outils, même historique de
    conversation) plutôt que de dupliquer cette logique de routage."""
    for matcher, tool_executor in routes_directes:
        tools = matcher(question)
        if tools is not None:
            return llm.ask_tool_direct(
                question, tools=tools, tool_executor=tool_executor, on_tool_call=on_tool_call
            )
    return llm.ask_with_tools(
        question, tools=tools_disponibles, tool_executor=executer_outil, on_tool_call=on_tool_call
    )


def main() -> None:
    args = parse_args()

    print("Chargement des modèles (ça peut prendre quelques secondes)...")
    detector = WakeWordDetector()
    stt = SpeechToText()
    tts = TextToSpeech()
    vad = VoiceActivityDetector()

    print("==== Modules ====")
    ha_client: HomeAssistantClient | None = None
    if config.HA_ENABLED:
        try:
            ha_client = HomeAssistantClient()
            print("✅ Connecté à Home Assistant.")
        except RuntimeError as exc:
            print(f"⚠️  Domotique désactivée : {exc}")
    else:
        print("⏸️  Domotique désactivée (home_assistant.enabled: false).")

    weather_client: WeatherClient | None = None
    if config.WEATHER_ENABLED:
        try:
            weather_client = WeatherClient()
            print(f"✅ Météo activée pour {config.LOCATION_CITY}.")
        except RuntimeError as exc:
            print(f"⚠️  Météo désactivée : {exc}")
    else:
        print("⏸️  Météo désactivée (weather.enabled: false).")

    def annoncer_alerte(texte: str) -> None:
        """Appelé (dans le thread de sondage de AlertesMeteoClient) dès
        qu'une nouvelle alerte météo apparaît dans le flux — jamais pour une
        alerte déjà annoncée. play_audio() sérialise avec le reste (réponses,
        minuteurs) via le même verrou."""
        message = f"Alerte météo : {texte}"
        print(f"\n🚨 Jarvis  : {message}\n")
        play_audio(tts.synthesize(message), tts.sample_rate)

    alertes_client: AlertesMeteoClient | None = None
    if config.ALERTS_ENABLED:
        try:
            alertes_client = AlertesMeteoClient(on_nouvelle_alerte=annoncer_alerte)
            print("✅ Alertes météo activées.")
        except RuntimeError as exc:
            print(f"⚠️  Alertes météo désactivées : {exc}")
    else:
        print("⏸️  Alertes météo désactivées (alerts.enabled: false).")

    boite_notifications = satellite_api.BoiteNotifications()
    sonnerie_audio = generer_sonnerie(tts.sample_rate)

    def annoncer_fin_minuteur(label: str, origine: str | None) -> None:
        """Appelé dans le thread du minuteur : sonne sur ce PC (play_audio
        sérialise avec les réponses en cours) ou, si un satellite l'a demandé,
        dépose le son dans sa boîte (il vient le chercher, voir satellite_api)."""
        message = f"Le minuteur {label} est terminé." if label else "Le minuteur est terminé."
        audio = np.concatenate([sonnerie_audio, tts.synthesize(message)])
        if origine is None:
            print(f"\n🔔 Jarvis  : {message}\n")
            play_audio(audio, tts.sample_rate)
        else:
            print(f"\n🔔 Jarvis ({origine}) : {message}\n")
            boite_notifications.deposer(origine, audio, tts.sample_rate)

    timer_manager = TimerManager(on_expire=annoncer_fin_minuteur)

    def construire_pile(origine: str | None):
        """Routes directes + outils du LLM, liés à l'appareil qui parle."""
        routes = construire_routes_directes(
            ha_client, weather_client, timer_manager, alertes_client, origine
        )
        outils, executeur = construire_outils(
            ha_client, weather_client, timer_manager, alertes_client, origine
        )
        return routes, outils, executeur

    routes_directes, tools_disponibles, executer_outil = construire_pile(None)

    if config.DASHBOARD_ENABLED:
        dashboard_url = dashboard.demarrer(config.DASHBOARD_PORT)
        print(f"📊 Panneau de ressources : {dashboard_url}")
    else:
        print("📊 Panneau de ressources désactivé (dashboard.enabled: false).")

    llm = LanguageModel(system_prompt=construire_system_prompt(ha_client))

    def prechauffer_llm() -> None:
        try:
            llm.warm_up()
        except Exception as exc:  # noqa: BLE001 - Ollama arrêté : la 1re question échouera de toute façon
            print(f"⚠️  Ollama injoignable ({exc!r}) : lance-le, puis relance Jarvis.")

    threading.Thread(target=prechauffer_llm, daemon=True).start()

    # Un seul tour de conversation à la fois (micro local et satellites
    # partagent le même historique LLM).
    verrou_conversation = threading.Lock()

    def repondre_flux(question: str, zone: str) -> Iterator[str]:
        """Passée à satellite_api.demarrer : la réponse du LLM, phrase par
        phrase ; la synthèse et l'envoi sont gérés côté satellite_api."""
        routes, outils, executeur = construire_pile(zone)
        return sous_verrou(
            verrou_conversation, choisir_reponse(question, llm, routes, outils, executeur)
        )

    if config.SATELLITE_ENABLED:
        if len(config.SATELLITE_API_KEY) < satellite_api.CLE_API_LONGUEUR_MIN:
            print(
                "⚠️  API satellite désactivée : satellite.api_key manquant ou trop courte "
                f"(min. {satellite_api.CLE_API_LONGUEUR_MIN} caractères, voir generate_api_key.py)."
            )
        else:
            try:
                url_satellite = satellite_api.demarrer(stt, tts, repondre_flux, boite_notifications)
                print(f"📡 API satellite : {url_satellite}")
            except RuntimeError as exc:
                print(f"⚠️  API satellite désactivée : {exc}.")
    else:
        print("⏸️  API satellite désactivée (satellite.enabled: false).")

    # Pré-synthétisées une fois pour toutes : évite de faire tourner Piper
    # (et donc d'ajouter de la latence) à chaque déclenchement du mot-clé ou
    # appel d'outil.
    salutation_audio = tts.synthesize(config.WAKE_WORD_PROMPT)
    tool_call_audios = {
        phrase: tts.synthesize(phrase) for phrase in config.LLM_TOOL_CALL_PHRASES
    }

    # Open WebUI et la vérification de version sont gérés par launch.py :
    # on n'affiche que leur état.
    print(f"{'✅' if config.OPEN_WEBUI_ENABLED else '⏸️ '} Open WebUI (géré par launch.py)")
    print(f"{'✅' if config.UPDATE_CHECK_ENABLED else '⏸️ '} Vérification de version (gérée par launch.py)\n")

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
            resultat_ecoute = {"audio": np.zeros(0, dtype=np.float32)}

            def _ecouter_pendant_la_salutation() -> None:
                resultat_ecoute["audio"] = record_until_silence(
                    vad, debug=args.debug_audio, no_speech_timeout=config.CONVERSATION_FIRST_TIMEOUT
                )

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
                echec = False
                try:
                    with verrou_conversation:
                        fragments = choisir_reponse(
                            question, llm, routes_directes, tools_disponibles, executer_outil,
                            on_tool_call,
                        )
                        parler_en_flux(fragments, tts, file_audio)
                except Exception as exc:  # noqa: BLE001 - Ollama arrêté, outil en erreur...
                    print(f"\n[erreur] {exc!r}")
                    echec = True
                    file_audio.put(None)  # sans effet si parler_en_flux l'a déjà posée
                print()

                thread_lecture.join()
                if echec:
                    play_audio(tts.synthesize(ERREUR_VOCALE), tts.sample_rate)
                    break
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
            time.sleep(PAUSE_APRES_ERREUR_S)


if __name__ == "__main__":
    main()
