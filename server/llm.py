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

    def ask_with_tools(
        self,
        question: str,
        tools: list[dict],
        tool_executor: Callable[[str, dict], str],
        max_rounds: int = 3,
        on_tool_call: Callable[[], None] | None = None,
    ) -> Iterator[str]:
        """Diffuse la réponse du LLM morceau par morceau, en le laissant
        appeler des outils avant de répondre : la synthèse vocale peut
        commencer avant la fin de la génération.

        Les appels d'outils (et leurs résultats) restent locaux à cet appel :
        seules la question et la réponse finale sont gardées dans l'historique.

        `on_tool_call`, si fourni, est appelé une seule fois, dès qu'un outil
        va être exécuté — pour une phrase d'attente ("Je vérifie ça...").
        Jamais appelé pour une réponse purement conversationnelle.

        Pour un outil dont le résultat est déjà une phrase prête à être dite,
        voir `ask_tool_direct` : plus fiable et plus rapide."""
        messages = self._messages_completes(question)
        accuse_donne = False

        for _ in range(max_rounds):
            fragments: list[str] = []
            tool_calls: list = []
            for chunk in ollama.chat(
                model=self.model, messages=messages, tools=tools, stream=True,
                keep_alive=config.LLM_KEEP_ALIVE,
            ):
                message = chunk["message"]
                delta = message.get("content")
                if delta:
                    fragments.append(delta)
                    yield delta
                tool_calls.extend(message.get("tool_calls") or [])

            if not tool_calls:
                self._enregistrer_echange(question, "".join(fragments))
                return

            if not accuse_donne and on_tool_call is not None:
                accuse_donne = True
                on_tool_call()

            messages.append(
                {"role": "assistant", "content": "".join(fragments), "tool_calls": tool_calls}
            )
            for call in tool_calls:
                nom = call["function"]["name"]
                resultat = tool_executor(nom, call["function"]["arguments"])
                messages.append({"role": "tool", "tool_name": nom, "content": str(resultat)})

        # max_rounds atteint sans réponse finale (le LLM n'a fait qu'appeler
        # des outils) : on lui redemande une conclusion, sans nouvel outil.
        fragments = []
        for chunk in ollama.chat(
            model=self.model, messages=messages, stream=True, keep_alive=config.LLM_KEEP_ALIVE
        ):
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
        est déjà une phrase prête à être dite (météo, date/heure, minuteur...) :
        on s'arrête après l'appel d'outil, sans redemander au LLM de la
        reformuler. Sinon qwen2.5:7b invente parfois un gabarit non rempli
        ("[jour], [mois]") ou bascule en anglais.

        Le LLM ne sert qu'à extraire les arguments : s'il répond en texte
        libre sans appeler l'outil, ce texte est ignoré (hallucination) et
        l'outil est appelé sans argument. `tools` ne contient donc qu'un
        seul outil, dont l'exécuteur gère proprement un argument manquant.

        Jamais d'historique envoyé au modèle : sur une question de suivi,
        qwen2.5:7b répond "de mémoire" au lieu de rappeler l'outil (valeur
        périmée, ou confirmation d'action jamais exécutée). Le tour reste
        mémorisé pour la suite (voir _enregistrer_echange)."""
        messages = [self._system_message, {"role": "user", "content": question}]
        response = ollama.chat(
            model=self.model, messages=messages, tools=tools, keep_alive=config.LLM_KEEP_ALIVE
        )
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

    def warm_up(self) -> None:
        """Charge le modèle en VRAM (sans rien générer) : la première question
        ne paie pas le chargement. Lève une exception si Ollama est
        indisponible."""
        ollama.generate(model=self.model, prompt="", keep_alive=config.LLM_KEEP_ALIVE)

    def reset_history(self) -> None:
        """Efface l'historique de conversation en cours (pour cette session)."""
        self.history = []
