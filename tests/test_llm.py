"""Tests pour llm.py : dispatch d'outils et déclenchement de on_tool_call,
avec ollama.chat entièrement mocké (aucun appel réseau ni serveur Ollama requis)."""
from unittest.mock import patch

from llm import LanguageModel, demande_de_reset


def _lm_factice() -> LanguageModel:
    """Construit un LanguageModel sans passer par __init__ (donc sans appel
    réseau au constructeur)."""
    lm = LanguageModel.__new__(LanguageModel)
    lm.model = "test"
    lm._system_message = {"role": "system", "content": "sys"}
    lm.history = []
    return lm


def test_demande_de_reset_detecte_les_phrases_connues():
    assert demande_de_reset("Hey Jarvis, oublie tout stp")
    assert demande_de_reset("Réinitialise ta mémoire")
    assert not demande_de_reset("Quelle heure est-il ?")


class _Message(dict):
    """Imite le SubscriptableBaseModel d'ollama (accès par .get())."""

    def get(self, cle, defaut=None):
        return super().get(cle, defaut)


def _flux(*messages):
    """Imite le flux de ollama.chat(stream=True) : un chunk par message."""
    return iter([{"message": _Message(**m)} for m in messages])


def _appel_outil(nom="obtenir_meteo"):
    return {"function": {"name": nom, "arguments": {}}}


def test_ask_with_tools_sans_outil_ne_declenche_jamais_on_tool_call():
    """Une réponse purement conversationnelle (aucun tool_call) ne doit pas
    déclencher la phrase d'attente, même si des outils sont disponibles."""
    appels = []

    def fake_chat(model, messages, tools=None, stream=False, keep_alive=None):
        return _flux({"content": "Bon"}, {"content": "jour."})

    lm = _lm_factice()
    with patch("llm.ollama.chat", side_effect=fake_chat) as mock_chat:
        fragments = list(
            lm.ask_with_tools(
                "salut",
                tools=[{"x": 1}],
                tool_executor=lambda n, a: "r",
                on_tool_call=lambda: appels.append(1),
            )
        )

    assert fragments == ["Bon", "jour."]
    assert appels == []
    mock_chat.assert_called_once()  # pas de second appel redondant
    assert lm.history[-1] == {"role": "assistant", "content": "Bonjour."}


def test_ask_with_tools_diffuse_avant_la_fin_de_la_generation():
    """Le 1er fragment doit sortir avant que le LLM ait fini : c'est tout
    l'intérêt du streaming pour commencer à parler tôt."""
    produits = []

    def flux():
        for morceau in ("Un. ", "Deux."):
            produits.append(morceau)
            yield {"message": _Message(content=morceau)}

    lm = _lm_factice()
    with patch("llm.ollama.chat", return_value=flux()):
        reponse = lm.ask_with_tools("salut", tools=[{"x": 1}], tool_executor=lambda n, a: "r")
        assert next(reponse) == "Un. "

    assert produits == ["Un. "]


def test_ask_with_tools_avec_outil_declenche_on_tool_call_une_fois():
    appels = []
    flux_par_tour = iter(
        [
            _flux({"tool_calls": [_appel_outil()]}),
            _flux({"content": "Il fait beau."}),
        ]
    )

    lm = _lm_factice()
    with patch("llm.ollama.chat", side_effect=lambda **kw: next(flux_par_tour)):
        fragments = list(
            lm.ask_with_tools(
                "quel temps fait-il ?",
                tools=[{"x": 1}],
                tool_executor=lambda n, a: "ok",
                on_tool_call=lambda: appels.append(1),
            )
        )

    assert fragments == ["Il fait beau."]
    assert appels == [1]  # déclenché une seule fois, pas à chaque outil/tour


def test_ask_with_tools_renvoie_le_resultat_de_l_outil_au_llm():
    envoyes = []
    flux_par_tour = iter([_flux({"tool_calls": [_appel_outil()]}), _flux({"content": "Ok."})])

    def fake_chat(**kw):
        envoyes.append([dict(m) if isinstance(m, dict) else m for m in kw["messages"]])
        return next(flux_par_tour)

    lm = _lm_factice()
    with patch("llm.ollama.chat", side_effect=fake_chat):
        list(lm.ask_with_tools("meteo ?", tools=[{"x": 1}], tool_executor=lambda n, a: "Il pleut."))

    dernier = envoyes[1][-1]
    assert dernier == {"role": "tool", "tool_name": "obtenir_meteo", "content": "Il pleut."}


def test_ask_with_tools_sans_on_tool_call_ne_plante_pas():
    """on_tool_call est optionnel : son absence ne doit rien casser.
    max_rounds=1 fait sortir de la boucle sans réponse finale, ce qui
    déclenche l'appel de repli sans outil."""
    lm = _lm_factice()
    flux_par_tour = iter([_flux({"tool_calls": [_appel_outil()]}), _flux({"content": "Voilà."})])

    with patch("llm.ollama.chat", side_effect=lambda **kw: next(flux_par_tour)):
        fragments = list(
            lm.ask_with_tools(
                "quel temps fait-il ?",
                tools=[{"x": 1}],
                tool_executor=lambda n, a: "ok",
                max_rounds=1,
            )
        )

    assert fragments == ["Voilà."]


def test_ask_tool_direct_relaie_le_resultat_sans_reformulation():
    """ask_tool_direct ne redemande jamais au LLM de reformuler le résultat
    de l'outil : la phrase de l'outil est relayée telle quelle, en un seul
    appel à ollama.chat (pas de second aller-retour)."""
    appels = []

    def fake_chat(model, messages, tools=None, stream=False, keep_alive=None):
        return {
            "message": _Message(
                tool_calls=[{"function": {"name": "obtenir_date_heure", "arguments": {}}}]
            )
        }

    lm = _lm_factice()
    with patch("llm.ollama.chat", side_effect=fake_chat) as mock_chat:
        fragments = list(
            lm.ask_tool_direct(
                "quelle heure est-il ?",
                tools=[{"x": 1}],
                tool_executor=lambda n, a: "Il est 8 heures 58.",
                on_tool_call=lambda: appels.append(1),
            )
        )

    assert fragments == ["Il est 8 heures 58."]
    assert appels == [1]
    mock_chat.assert_called_once()  # aucun second appel de reformulation


def test_ask_tool_direct_sans_historique_mais_memorise_lechange():
    """Le message envoyé au LLM ne contient ni system_prompt+historique
    complet, juste la question — mais le tour est quand même mémorisé pour
    la suite de la conversation."""
    lm = _lm_factice()
    lm.history = [{"role": "user", "content": "vieille question"}, {"role": "assistant", "content": "vieille réponse"}]

    def fake_chat(model, messages, tools=None, stream=False, keep_alive=None):
        return {
            "message": _Message(
                tool_calls=[{"function": {"name": "obtenir_date_heure", "arguments": {}}}]
            )
        }

    with patch("llm.ollama.chat", side_effect=fake_chat) as mock_chat:
        fragments = list(
            lm.ask_tool_direct(
                "quelle heure est-il ?",
                tools=[{"x": 1}],
                tool_executor=lambda n, a: "Il est 8 heures 58.",
            )
        )

    assert fragments == ["Il est 8 heures 58."]
    _, kwargs = mock_chat.call_args
    assert kwargs["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "quelle heure est-il ?"},
    ]
    assert lm.history[-2:] == [
        {"role": "user", "content": "quelle heure est-il ?"},
        {"role": "assistant", "content": "Il est 8 heures 58."},
    ]


def test_ask_tool_direct_sans_appel_d_outil_appelle_loutil_lui_meme():
    """Garde-fou principal : si le LLM répond en texte libre sans appeler
    l'outil (le modèle invente alors un gabarit non rempli, ex: "[jour],
    [mois] [année]"), ce texte est ignoré : l'outil est appelé sans argument
    et sa réponse déterministe est utilisée."""
    lm = _lm_factice()

    def fake_chat(model, messages, tools=None, stream=False, keep_alive=None):
        return {"message": _Message(content="On est le [jour], [mois] [année].", tool_calls=None)}

    outil_tools = [{"type": "function", "function": {"name": "obtenir_date_heure"}}]

    with patch("llm.ollama.chat", side_effect=fake_chat):
        fragments = list(
            lm.ask_tool_direct(
                "on est quel jour ?",
                tools=outil_tools,
                tool_executor=lambda n, a: "Nous sommes le lundi 14 septembre 2026.",
            )
        )

    assert fragments == ["Nous sommes le lundi 14 septembre 2026."]


def test_ask_tool_direct_sans_parametre_n_appelle_pas_le_llm():
    """Aucun argument à extraire (ex: alertes météo) : un aller-retour LLM
    ne ferait que retarder la réponse."""
    lm = _lm_factice()
    outil = [{"type": "function", "function": {"name": "alerte", "parameters": {"type": "object", "properties": {}}}}]

    with patch("llm.ollama.chat") as mock_chat:
        fragments = list(lm.ask_tool_direct("y a-t-il une alerte ?", tools=outil, tool_executor=lambda n, a: "Aucune."))

    assert fragments == ["Aucune."]
    mock_chat.assert_not_called()
    assert lm.history[-1] == {"role": "assistant", "content": "Aucune."}
