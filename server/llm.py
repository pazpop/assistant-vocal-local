"""Module LLM utilisant Ollama comme serveur d'inférence local."""
from typing import Callable, Iterator

import ollama

import config
from trigger import contient_une_phrase


def demande_de_reset(texte: str) -> bool:
    """Détecte si une phrase transcrite demande de réinitialiser l'historique
    de conversation en cours (ex: "oublie tout")."""
    return contient_une_phrase(texte, config.MEMORY_RESET_PHRASES)


class LanguageModel:
    def __init__(
        self,
        model: str = config.LLM_MODEL,
        system_prompt: str | None = None,
    ):
        if system_prompt is None:
            system_prompt = config.LLM_SYSTEM_PROMPT_TEMPLATE.format(
                appareils="(Home Assistant non configuré)"
            )
        self.model = model
        # Le system prompt n'est jamais persisté : il est reconstruit à
        # chaque lancement (ex: liste à jour des appareils Home Assistant).
        self._system_message = {"role": "system", "content": system_prompt}

        # Historique de conversation, gardé en mémoire pour la durée de la
        # session uniquement (voir reset_history) — pas de persistance sur
        # disque : à chaque lancement, Jarvis repart sans historique.
        self.history: list[dict] = []

    def _messages_completes(self, question: str) -> list[dict]:
        return [self._system_message] + self.history + [{"role": "user", "content": question}]

    def _tronquer_historique(self) -> None:
        """Ne garde que les N derniers échanges (config.CONVERSATION_MAX_ECHANGES),
        pour ne pas faire grossir indéfiniment le contexte envoyé au LLM à
        chaque tour (latence + risque de saturer sa fenêtre de contexte)."""
        max_messages = config.CONVERSATION_MAX_ECHANGES * 2  # 2 messages par échange
        if len(self.history) > max_messages:
            self.history = self.history[-max_messages:]

    def _enregistrer_echange(self, question: str, reponse: str) -> None:
        self.history.append({"role": "user", "content": question})
        self.history.append({"role": "assistant", "content": reponse})
        self._tronquer_historique()

    def ask_stream(self, question: str, keep_history: bool = True) -> Iterator[str]:
        """Diffuse la réponse du LLM morceau par morceau (générateur), sans outils.

        Permet de commencer la synthèse vocale avant que le LLM ait fini de
        répondre : on n'attend plus la réponse complète pour parler.
        """
        messages = self._messages_completes(question)
        fragments: list[str] = []

        for chunk in ollama.chat(model=self.model, messages=messages, stream=True):
            delta = chunk["message"]["content"]
            if delta:
                fragments.append(delta)
                yield delta

        if keep_history:
            self._enregistrer_echange(question, "".join(fragments))

    def ask_with_tools(
        self,
        question: str,
        tools: list[dict],
        tool_executor: Callable[[str, dict], str],
        max_rounds: int = 3,
        on_tool_call: Callable[[], None] | None = None,
    ) -> Iterator[str]:
        """Comme ask_stream, mais laisse le LLM appeler des outils avant de répondre.

        Les éventuels appels d'outils (et leurs résultats) restent locaux à
        cet appel : seules la question et la réponse finale sont mémorisées
        d'une session à l'autre, pas le détail des outils exécutés (états
        d'appareils éphémères, peu utiles à retenir).

        `on_tool_call`, si fourni, est appelé une seule fois, dès qu'on sait
        qu'au moins un outil va être exécuté (avant de l'exécuter) — pensé
        pour déclencher une phrase d'attente ("Je vérifie ça...") pendant
        l'appel réseau qui suit, sans jamais se déclencher pour une réponse
        purement conversationnelle qui n'a besoin d'aucun outil.

        Pour un outil dont le résultat est déjà une phrase prête à être dite
        (météo, date/heure), voir `ask_tool_direct` à la place : plus fiable
        et plus rapide, car il évite de redemander au LLM de la reformuler.
        """
        messages = self._messages_completes(question)
        accuse_donne = False

        for _ in range(max_rounds):
            response = ollama.chat(model=self.model, messages=messages, tools=tools)
            message = response["message"]
            tool_calls = message.get("tool_calls")

            if not tool_calls:
                # Le LLM a directement répondu en texte : cette réponse (déjà
                # complète) est la réponse finale, pas la peine de la
                # regénérer via un second appel identique en streaming.
                contenu = message.get("content") or ""
                if contenu:
                    yield contenu
                self._enregistrer_echange(question, contenu)
                return

            if not accuse_donne and on_tool_call is not None:
                accuse_donne = True
                on_tool_call()

            messages.append(message)
            for call in tool_calls:
                nom = call["function"]["name"]
                arguments = call["function"]["arguments"]
                resultat = tool_executor(nom, arguments)
                messages.append({"role": "tool", "tool_name": nom, "content": str(resultat)})
        # max_rounds atteint sans réponse finale (le LLM n'a fait qu'appeler
        # des outils) : on lui redemande une conclusion, sans nouvel outil.

        fragments: list[str] = []
        for chunk in ollama.chat(model=self.model, messages=messages, stream=True):
            delta = chunk["message"]["content"]
            if delta:
                fragments.append(delta)
                yield delta

        self._enregistrer_echange(question, "".join(fragments))

    def ask_tool_direct(
        self,
        question: str,
        tools: list[dict],
        tool_executor: Callable[[str, dict], str],
        on_tool_call: Callable[[], None] | None = None,
    ) -> Iterator[str]:
        """Comme ask_with_tools, mais pour un UNIQUE outil dont le résultat
        est déjà une phrase complète prête à être dite (météo, date/heure) :
        on s'arrête après l'appel d'outil, sans redemander au LLM de la
        reformuler.

        Ce second aller-retour était un vrai point de défaillance : même sans
        historique, qwen2.5:7b invente parfois un gabarit non rempli (ex:
        "[jour], [mois] [année]") ou bascule en anglais au lieu de relayer la
        vraie valeur reçue de l'outil. Le supprimer élimine le risque et
        économise un appel réseau.

        Deuxième garde-fou, tout aussi important : si le LLM répond en texte
        libre SANS appeler l'outil (constaté en pratique malgré la consigne
        "Appelle TOUJOURS cet outil" — surtout avec le vrai prompt système,
        plus long, qui liste plusieurs autres outils), ce texte libre est
        halluciné exactement de la même façon (mêmes gabarits non remplis).
        On ne lui fait donc jamais confiance : dans ce cas, l'outil est
        appelé nous-mêmes, sans argument. `tools` ne doit donc contenir
        qu'un seul outil, soit avec des paramètres tous optionnels (vrai pour
        WEATHER_TOOLS/DATE_HEURE_TOOLS), soit dont l'exécuteur gère
        proprement un argument requis manquant plutôt que de planter (vrai
        pour TIMER_TOOLS, qui renvoie alors un message clair plutôt qu'une
        fausse confirmation) — la réponse est alors toujours déterministe,
        jamais un texte inventé.

        Jamais d'historique envoyé (comme l'ancien use_history=False) : rien
        à réutiliser d'une question précédente, donc rien à halluciner. Le
        tour reste quand même mémorisé pour la suite de la conversation.
        """
        messages = [self._system_message, {"role": "user", "content": question}]
        response = ollama.chat(model=self.model, messages=messages, tools=tools)
        message = response["message"]
        tool_calls = message.get("tool_calls") or [
            {"function": {"name": tools[0]["function"]["name"], "arguments": {}}}
        ]

        if on_tool_call is not None:
            on_tool_call()

        resultats = [
            str(tool_executor(call["function"]["name"], call["function"]["arguments"]))
            for call in tool_calls
        ]
        reponse = " ".join(resultats)
        yield reponse
        self._enregistrer_echange(question, reponse)

    def reset_history(self) -> None:
        """Efface l'historique de conversation en cours (pour cette session)."""
        self.history = []
