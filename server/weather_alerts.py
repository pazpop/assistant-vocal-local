"""Alertes météo publiques du gouvernement du Canada, via un flux Atom
gratuit (aucune clé API, aucun compte) :
https://www.canada.ca/en/environment-climate-change/services/weather-general-tools-resources/weatheroffice-online-services/atom-feeds.html

Chaque région a sa propre URL de flux (trouve la tienne sur la page
ci-dessus). Privilégie l'URL se terminant par "_f.xml" (français) plutôt que
"_e.xml" (anglais), pour rester cohérent avec les réponses parlées de Jarvis.

Désactivé si `alerts.feed_url` est vide dans config.yml (pas de région
configurée = pas de fonctionnalité, comme Home Assistant sans jeton).
"""
import re
import threading
import time
from datetime import datetime
from datetime import time as heure
from typing import Callable
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import requests

import config
from trigger import contient_une_phrase

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}

# Sentinelles utilisées par Environnement Canada quand rien n'est en vigueur,
# en français et en anglais (au cas où le flux configuré est la version
# anglaise "_e.xml").
AUCUNE_ALERTE_MARQUEURS = ("aucune alerte", "no alerts in effect")

# Outil exposé au LLM (même format que WEATHER_TOOLS). Pas de paramètre :
# contrairement à la météo, le flux est déjà spécifique à une seule région
# choisie dans config.yml, pas de "ville" à préciser.
ALERT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "obtenir_alerte_meteo",
            "description": (
                "Donne les alertes météo publiques (tempête, froid extrême, "
                "etc.) en vigueur pour la région configurée. Appelle "
                "TOUJOURS cet outil pour toute question sur une alerte ou un "
                "avertissement météo."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

# Phrases qui déclenchent une question d'alerte météo (comparaison en
# minuscules). Comme pour la météo/date-heure/minuteur/domotique (voir
# weather.py), utilisées pour envoyer la question au LLM sans historique de
# conversation via llm.ask_tool_direct.
ALERT_TRIGGER_PHRASES = (
    "alerte météo",
    "alerte meteo",
    "avertissement météo",
    "avertissement meteo",
    "vigilance météo",
)


def demande_alerte(texte: str) -> bool:
    """Détecte si une phrase transcrite demande les alertes météo en cours."""
    return contient_une_phrase(texte, ALERT_TRIGGER_PHRASES)


def _nettoyer_html(texte: str) -> str:
    """Retire les balises HTML éventuelles du résumé d'alerte (le flux les
    autorise dans <summary type="html">), pour rester audible tel quel."""
    return re.sub(r"<[^>]+>", "", texte).strip()


def _dans_la_periode_silencieuse(maintenant: heure | None = None) -> bool:
    """Vrai si l'heure actuelle tombe dans la période où l'annonce PROACTIVE
    est coupée (`alerts.quiet_hours_start`/`_end`, ex: 22h-8h) — gère le
    passage de minuit. `maintenant` n'est là que pour les tests ; en usage
    réel, c'est toujours l'heure actuelle dans le fuseau `location.timezone`
    (pas l'horloge système, pour la même raison que date_time.py)."""
    debut = datetime.strptime(config.ALERTS_QUIET_HOURS_START, "%H:%M").time()
    fin = datetime.strptime(config.ALERTS_QUIET_HOURS_END, "%H:%M").time()
    if debut == fin:
        return False  # période nulle : jamais de coupure

    if maintenant is None:
        maintenant = datetime.now(ZoneInfo(config.LOCATION_TIMEZONE)).time()

    if debut < fin:
        return debut <= maintenant < fin
    return maintenant >= debut or maintenant < fin  # la période traverse minuit


class AlertesMeteoClient:
    def __init__(
        self,
        feed_url: str = config.ALERTS_FEED_URL,
        on_nouvelle_alerte: Callable[[str], None] | None = None,
        intervalle_minutes: float = config.ALERTS_CHECK_INTERVAL_MINUTES,
    ):
        if not feed_url:
            raise RuntimeError(
                "Aucune URL de flux d'alertes configurée. Trouve celle de ta "
                "région sur https://www.canada.ca/en/environment-climate-"
                "change/services/weather-general-tools-resources/"
                "weatheroffice-online-services/atom-feeds.html, puis "
                "renseigne-la dans 'alerts.feed_url' de config.yml."
            )
        self.feed_url = feed_url
        self._dernier_id_annonce: str | None = None

        # Valide la connectivité et le format dès le démarrage, comme le
        # géocodage pour la météo — mieux vaut échouer tôt avec un message
        # clair qu'au premier "y a-t-il une alerte ?".
        self.obtenir_alerte()

        if on_nouvelle_alerte is not None and intervalle_minutes > 0:
            threading.Thread(
                target=self._sonder_periodiquement,
                args=(on_nouvelle_alerte, intervalle_minutes),
                daemon=True,
            ).start()

    def _recuperer_premiere_entree(self) -> tuple[str, str, str]:
        """Récupère (titre, résumé, id) de la première entrée du flux — pour
        les flux d'Environnement Canada, c'est toujours la plus récente."""
        try:
            reponse = requests.get(self.feed_url, timeout=5)
            reponse.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Impossible de contacter le flux d'alertes météo "
                f"({self.feed_url}). Détail : {exc}"
            ) from exc

        racine = ElementTree.fromstring(reponse.content)
        entree = racine.find("atom:entry", ATOM_NS)
        if entree is None:
            raise RuntimeError("Flux d'alertes météo vide ou mal formé.")

        titre = (entree.findtext("atom:title", default="", namespaces=ATOM_NS) or "").strip()
        resume = entree.findtext("atom:summary", default="", namespaces=ATOM_NS) or ""
        id_entree = (entree.findtext("atom:id", default="", namespaces=ATOM_NS) or "").strip()
        return titre, _nettoyer_html(resume), id_entree

    def obtenir_alerte(self, ville: str | None = None) -> str:
        """Renvoie une phrase prête à être dite : soit qu'aucune alerte n'est
        en vigueur, soit le titre + résumé de l'alerte active. `ville` est
        ignoré (le flux est déjà spécifique à une seule région, configurée
        dans config.yml) — présent seulement pour la cohérence de signature
        avec les autres outils du tool-calling."""
        titre, resume, _ = self._recuperer_premiere_entree()
        if any(marqueur in titre.lower() for marqueur in AUCUNE_ALERTE_MARQUEURS):
            return "Aucune alerte météo en vigueur."
        return f"{titre}. {resume}".strip()

    def _sonder_periodiquement(
        self, on_nouvelle_alerte: Callable[[str], None], intervalle_minutes: float
    ) -> None:
        """Tourne dans un thread à part, indéfiniment : vérifie le flux à
        intervalle régulier et déclenche `on_nouvelle_alerte` une seule fois
        par alerte (jamais deux fois pour la même), dès qu'elle apparaît —
        sans que l'utilisateur ait à demander.

        Le `try/except` large (comme dans la boucle principale de main.py)
        est volontaire : sans lui, une erreur inattendue dans
        `on_nouvelle_alerte` (ex: échec ponctuel de synthèse vocale) tuerait
        ce thread pour de bon — plus aucune alerte proactive pour le reste
        de la session, sans message d'erreur visible."""
        while True:
            time.sleep(intervalle_minutes * 60)
            try:
                self._sonder_une_fois(on_nouvelle_alerte)
            except Exception as exc:  # noqa: BLE001 - le sondage doit survivre à une erreur ponctuelle
                print(f"[alertes météo] erreur pendant le sondage : {exc!r}")

    def _sonder_une_fois(self, on_nouvelle_alerte: Callable[[str], None]) -> None:
        """Une seule vérification du flux : appelle `on_nouvelle_alerte` si
        (et seulement si) une alerte active et jamais vue est trouvée, et
        qu'on n'est pas dans la période silencieuse (ex: 22h-8h). Isolée de
        la boucle infinie de `_sonder_periodiquement` pour rester testable
        sans mocker `time.sleep`.

        Une alerte détectée pendant la période silencieuse est marquée comme
        vue SANS être annoncée, même une fois la coupure terminée : elle est
        ignorée, pas rattrapée au réveil. Seule une alerte réellement
        nouvelle (apparue après la fin de la période silencieuse) est lue à
        voix haute."""
        try:
            titre, resume, id_entree = self._recuperer_premiere_entree()
        except RuntimeError:
            return  # on retente simplement au prochain sondage

        est_active = not any(m in titre.lower() for m in AUCUNE_ALERTE_MARQUEURS)
        if not est_active or id_entree == self._dernier_id_annonce:
            return

        self._dernier_id_annonce = id_entree
        if _dans_la_periode_silencieuse():
            return  # alerte ignorée : apparue pendant la période silencieuse

        on_nouvelle_alerte(f"{titre}. {resume}".strip())

    def executer_outil(self, nom: str, arguments: dict) -> str:
        """Dispatch pour le tool-calling du LLM (même patron que les autres clients)."""
        if nom == "obtenir_alerte_meteo":
            return self.obtenir_alerte()
        return f"Outil alerte météo inconnu : {nom}"
