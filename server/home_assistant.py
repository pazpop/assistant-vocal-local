"""Client minimal pour l'API REST de Home Assistant.

But : piloter lampes et prises depuis Jarvis sans passer par un service
cloud tiers (ni Apple, ni un cloud domotique quelconque) : tout transite sur
ton réseau local, vers ton propre serveur Home Assistant (que ce soit une
VM, un Raspberry Pi ou une machine dédiée). HA reste la seule "brique tierce"
du système — mais c'est déjà ton serveur domotique auto-hébergé, donc le
compromis le plus raisonnable si tu ne veux pas réimplémenter toi-même les
protocoles Zigbee / Z-Wave / HomeKit de chaque appareil. Si tes appareils
sont aussi exposés à Siri/HomePods via l'intégration HomeKit de HA, ce
chemin-là continue de fonctionner en parallèle, indépendamment de Jarvis.

Prérequis : un jeton d'accès longue durée Home Assistant
(Profil > Sécurité > Jetons d'accès longue durée), renseigné dans
`home_assistant.token` de `config.yml` (jamais commité, jamais en dur dans
le code).
"""
import requests

import config
from trigger import contient_une_phrase

# Domaines que "allumer"/"eteindre" ont le droit de piloter. Le prompt système
# ne liste que ça au LLM, mais rien ne l'empêche d'halluciner un entity_id
# d'un autre domaine (ex: "lock.porte_entree") : cette liste est la vraie
# barrière, imposée par le code plutôt que par la seule bonne volonté du LLM.
DOMAINES_AUTORISES = {"light", "switch"}

# Phrases qui déclenchent une commande domotique (comparaison en minuscules),
# utilisées pour router vers llm.ask_tool_direct (voir la docstring de cette
# méthode pour le pourquoi de l'absence d'historique). "éteindre" est
# vérifié en premier : les deux listes ne se chevauchent pas, mais autant
# rester explicite plutôt que de se fier à cette absence.
ETEINDRE_TRIGGER_PHRASES = ("éteins", "éteint", "éteindre", "eteins", "eteint", "eteindre")
ALLUMER_TRIGGER_PHRASES = ("allume", "allumer")


def demande_domotique(texte: str) -> str | None:
    """Détecte si une phrase transcrite demande d'allumer ou d'éteindre un
    appareil, et renvoie le nom de l'outil correspondant ('allumer' ou
    'eteindre'), ou None si ce n'est pas une demande de domotique."""
    if contient_une_phrase(texte, ETEINDRE_TRIGGER_PHRASES):
        return "eteindre"
    if contient_une_phrase(texte, ALLUMER_TRIGGER_PHRASES):
        return "allumer"
    return None

# Outils exposés au LLM (format attendu par Ollama pour le tool-calling :
# https://ollama.com — un dict par outil, avec son schéma de paramètres JSON).
HA_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "allumer",
            "description": "Allume une lumière ou une prise connectée.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_id": {
                        "type": "string",
                        "description": "Identifiant Home Assistant, ex: light.salon",
                    },
                },
                "required": ["entity_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "eteindre",
            "description": "Éteint une lumière ou une prise connectée.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_id": {
                        "type": "string",
                        "description": "Identifiant Home Assistant, ex: switch.prise_bureau",
                    },
                },
                "required": ["entity_id"],
            },
        },
    },
]


class HomeAssistantClient:
    def __init__(
        self,
        base_url: str = config.HA_BASE_URL,
        token: str = config.HA_TOKEN,
        verify_ssl: bool = config.HA_VERIFY_SSL,
    ):
        if not token:
            raise RuntimeError(
                "Jeton Home Assistant manquant. Crée un jeton longue durée "
                "dans Home Assistant (Profil > Sécurité > Jetons d'accès "
                "longue durée), puis renseigne-le dans 'home_assistant.token' "
                "de config.yml, à la racine du projet."
            )
        self.base_url = base_url.rstrip("/")
        self.verify_ssl = verify_ssl
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        self._verifier_connexion()

    def _verifier_connexion(self) -> None:
        """Teste tôt que la VM Home Assistant est joignable, avec un message
        clair en cas d'échec (utile quand HA n'est plus sur la même machine :
        VM éteinte, IP qui a changé, pare-feu, certificat...)."""
        url = f"{self.base_url}/api/"
        try:
            reponse = requests.get(url, headers=self.headers, timeout=5, verify=self.verify_ssl)
        except requests.exceptions.SSLError as exc:
            raise RuntimeError(
                f"Certificat SSL refusé pour {self.base_url}. Si ta VM utilise "
                "un certificat auto-signé, passe home_assistant.verify_ssl: false "
                "dans config.yml (uniquement sur un réseau local de confiance)."
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise RuntimeError(
                f"Impossible de joindre la VM Home Assistant à {self.base_url}. "
                "Vérifie : (1) que l'IP dans home_assistant.base_url est la bonne (elle a pu "
                "changer si elle n'est pas fixe/réservée dans ton routeur), "
                "(2) que la VM est allumée et joignable (essaie `ping <IP>`), "
                "(3) qu'aucun pare-feu ne bloque le port 8123."
            ) from exc
        except requests.exceptions.Timeout as exc:
            raise RuntimeError(
                f"Délai dépassé (5s) en contactant {self.base_url}. La VM est "
                "peut-être éteinte, en veille, ou surchargée."
            ) from exc
        except requests.exceptions.RequestException as exc:  # ex: base_url vide ou sans http://
            raise RuntimeError(f"Adresse Home Assistant invalide ({self.base_url!r}) : {exc}") from exc

        if reponse.status_code == 401:
            raise RuntimeError(
                "Jeton Home Assistant refusé (401 Unauthorized). Vérifie qu'il "
                "n'a pas expiré ou été révoqué dans Home Assistant "
                "(Profil > Sécurité > Jetons d'accès longue durée)."
            )
        reponse.raise_for_status()

    def _appeler_service(self, domaine: str, service: str, entity_id: str, **extra) -> str:
        url = f"{self.base_url}/api/services/{domaine}/{service}"
        payload = {"entity_id": entity_id, **extra}
        reponse = requests.post(
            url, json=payload, headers=self.headers, timeout=5, verify=self.verify_ssl
        )
        reponse.raise_for_status()
        # Directement parlable (utilisé tel quel par llm.ask_tool_direct, sans
        # reformulation LLM) : nom court si un alias existe dans config.yml,
        # sinon l'entity_id brut. Volontairement sans accord grammatical
        # (masculin/féminin dépend de l'appareil, pas connu ici) : préférer
        # une confirmation fiable et sans ambiguïté à une formulation plus
        # élégante mais qui obligerait à redemander au LLM.
        nom = config.HA_DEVICE_ALIASES.get(entity_id, entity_id)
        etat = "allumé" if service == "turn_on" else "éteint"
        return f"{nom} : {etat}."

    def lister_appareils(self, domaine: str) -> list[dict]:
        """Récupère tous les appareils d'un domaine Home Assistant (ex: 'light')."""
        url = f"{self.base_url}/api/states"
        reponse = requests.get(url, headers=self.headers, timeout=5, verify=self.verify_ssl)
        reponse.raise_for_status()
        return [e for e in reponse.json() if e["entity_id"].startswith(f"{domaine}.")]

    def executer_outil(self, nom: str, arguments: dict) -> str:
        """Dispatch un appel d'outil demandé par le LLM vers l'API Home Assistant.

        C'est cette méthode qu'on passe à LanguageModel.ask_with_tools comme
        `tool_executor` : elle prend le nom de l'outil + ses arguments, et
        retourne un résultat textuel que le LLM pourra lire avant de répondre.
        """
        try:
            if nom in ("allumer", "eteindre"):
                entity_id = arguments["entity_id"]
                domaine = entity_id.split(".")[0]
                if domaine not in DOMAINES_AUTORISES:
                    return (
                        f"Domaine '{domaine}' non autorisé pour cet outil "
                        f"(seuls {', '.join(sorted(DOMAINES_AUTORISES))} sont permis)."
                    )
                service = "turn_on" if nom == "allumer" else "turn_off"
                return self._appeler_service(domaine, service, entity_id)
            return f"Outil inconnu : {nom}"
        except KeyError as exc:
            return f"Argument manquant pour l'outil '{nom}' : {exc}"
        except requests.RequestException as exc:
            return f"Erreur en contactant Home Assistant : {exc}"
