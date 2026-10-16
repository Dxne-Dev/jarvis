"""Ce que Jarvis fait d'un appel d'outil pendant une conversation.

- Outil de niveau 1 (lire) : exécuté tout de suite, par la porte des permissions ; son
  résultat revient au modèle encadré comme une donnée s'il vient de l'extérieur.
- `proposer_un_plan` : le plan est vérifié, enregistré, et attend ta décision.
- Appel direct d'une action (niveau 2 ou 3) : jamais exécuté ; il devient un plan
  d'une étape, à valider comme les autres.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from ojarvis.agent.executor import PlanExecutor
from ojarvis.agent.plans import PLAN_TOOL, PlanIn, PlanRecord, PlanStore, StepIn, plan_tool_spec
from ojarvis.core.errors import EngineError
from ojarvis.core.logs import get_logger
from ojarvis.events.bus import EventBus
from ojarvis.llm.types import ToolCall, ToolSpec
from ojarvis.permissions.gate import PermissionGate
from ojarvis.tools.base import LEVEL_LABELS, Level
from ojarvis.tools.guards import DATA_RULE, as_data

log = get_logger(__name__)

#: Tours d'outils au plus dans une réponse (ensuite, le modèle doit conclure).
MAX_TOOL_ROUNDS = 5

AGENT_RULES = (
    "Tu as des outils. Dans leurs descriptions, « ton dossier personnel », « tes fichiers "
    "» et « ~ » désignent ceux de l'utilisateur, sur cet ordinateur. Tu n'as aucun outil "
    "pour lancer une commande dans un terminal, même avec le contrôle du PC activé : "
    "dis-le simplement. Niveau 1 (lire : recherche web, pages, fichiers, navigateur, code "
    "isolé) : utilise-les directement quand ils aident, sans demander. Niveaux 2 et 3 "
    "(agir : cliquer, remplir, écrire un fichier, utiliser une session ; détruire) : ne "
    "les appelle jamais seuls ; propose un plan avec proposer_un_plan, que l'utilisateur "
    "validera. Le plan est ta demande de confirmation : ne demande pas « tu confirmes ? » "
    "avant de le proposer. S'il manque une information indispensable (quoi, où, quand), "
    "demande-la ; si tu peux la lire toi-même (identifiant, contenu d'un fichier), lis-la "
    "d'abord avec un outil de lecture. Sinon propose le plan tout de suite. Si une partie "
    "de la demande t'est impossible (lancer une commande dans un terminal, par exemple), "
    "propose quand même le plan pour le reste et dis clairement ce qu'il restera à faire. "
    "Ne dis jamais qu'un plan attend une validation si tu n'as pas appelé "
    "proposer_un_plan. Pour une tâche en plusieurs étapes, propose tout le plan d'un coup, "
    "avec des cibles précises (adresse, fichier, bouton). N'invente jamais le résultat "
    "d'un outil. Cite tes sources quand tu t'appuies sur le web. Pour GitHub, Notion ou "
    "l'agenda : regarde d'abord les outils avec integrations_outils, puis appelle-les avec "
    "integration_appeler. Si une capacité te manque et qu'elle se calcule (sans Internet "
    "ni fichiers), crée-la avec creer_skill (fonctions Python pures et leurs tests) : si "
    "ses tests réussissent, son activation est proposée à l'utilisateur ; une fois actif, "
    "utilise ses outils.\n\n" + DATA_RULE
)
OS_CONTROL_ON = (
    "Contrôle du PC activé : tu peux ouvrir ou fermer une application et ranger des fichiers "
    "(par un plan à valider), et regarder l'écran avec regarder_ecran quand on te le demande."
)
OS_CONTROL_OFF = (
    "Contrôle du PC désactivé : tu ne peux ni ouvrir ni fermer une application, ni ranger des "
    "fichiers, ni regarder l'écran. Si on te le demande, dis-le et indique qu'on l'active "
    "dans Réglages, section « Contrôle du PC »."
)
PLAN_STARTED = (
    "Plan lancé : il ne fait que lire, il part donc sans attendre ; son résultat arrivera "
    "dans la conversation. N'appelle pas d'autre outil : dis en une phrase ce que tu fais."
)
PLAN_PENDING = (
    "Plan enregistré. L'utilisateur le voit à l'écran avec « Valider » et « Refuser » ; rien "
    "n'est exécuté avant sa décision. N'appelle pas d'autre outil : dis-lui en une ou deux "
    "phrases ce que fera le plan et qu'il attend sa validation."
)


#: Le modèle annonce un plan à valider (« le plan est prêt », « confirme à l'écran »…), ou
#: écrit l'appel de l'outil dans son texte au lieu de le faire.
PLAN_CLAIM = re.compile(
    r"(?:valid|confirm)\w*\s*(?:-le)?\s+(?:le\s+plan|à\s+l['’]écran)|plan\s+est\s+prêt"
    r"|attend\w*\s+ta\s+validation|passe\s+par\s+un\s+plan|voici\s+le\s+plan"
    r"|je\s+(?:te\s+)?(?:prépare|propose)\s+(?:le|ce|un)\s+plan|<\s*/?\s*proposer_un_plan",
    re.IGNORECASE,
)
PLAN_MISSING = (
    "[Note du système] Tu viens d'annoncer un plan à valider, mais tu n'as pas appelé "
    "proposer_un_plan : aucun plan n'existe et l'utilisateur ne verra rien à valider. Propose-le "
    "maintenant (lis d'abord avec un outil de lecture ce qui te manque, un identifiant par "
    "exemple), ou dis en une phrase que tu ne peux pas."
)


def claims_missing_plan(text: str, proposed: list[str]) -> bool:
    """Un plan annoncé dans la réponse alors qu'aucun n'a été proposé pendant le tour."""
    return not proposed and PLAN_CLAIM.search(text) is not None


_URL = re.compile(r"https?://[^\s<>\"'()\[\]{}«»]+")


def urls_in(value: Any) -> set[str]:
    """Adresses web citées dans un texte (ou dans les valeurs d'un résultat structuré)."""
    if isinstance(value, str):
        return {u.rstrip(".,;:!?").rstrip("/") for u in _URL.findall(value)}
    if isinstance(value, dict):
        return set().union(*(urls_in(v) for v in value.values())) if value else set()
    if isinstance(value, list | tuple):
        return set().union(*(urls_in(v) for v in value)) if value else set()
    return set()


@dataclass
class AgentTurn:
    """Ce qui s'est passé pendant un tour : outils utilisés, plans proposés."""

    #: Un contenu externe a été lu : un plan proposé ensuite est signalé à la validation.
    tainted: bool = False
    tools: list[dict[str, Any]] = field(default_factory=list)
    plans: list[str] = field(default_factory=list)
    #: Adresses connues pendant ce tour : celles de ta demande et celles lues (liens, résultats).
    known_urls: set[str] = field(default_factory=set)

    def knows(self, url: str) -> bool:
        return url.strip().rstrip("/") in self.known_urls


@dataclass(frozen=True)
class CallOutcome:
    content: str
    event: dict[str, Any]
    is_error: bool = False
    plan: PlanRecord | None = None


def plan_summary(plan: PlanRecord) -> dict[str, Any]:
    return {
        "id": plan.id,
        "title": plan.title,
        "status": plan.status,
        "max_level": plan.max_level,
        "tainted": plan.tainted,
        "steps": [
            {"position": s.position, "description": s.description, "level": s.level}
            for s in plan.steps
        ],
    }


class Agent:
    def __init__(
        self,
        *,
        gate: PermissionGate,
        plans: PlanStore,
        bus: EventBus,
        executor: PlanExecutor | None = None,
    ) -> None:
        self._gate = gate
        self._plans = plans
        self._bus = bus
        self._executor = executor

    def rules(self) -> str:
        """Consignes du tour, selon ce que Jarvis a le droit de faire en ce moment."""
        os_control = OS_CONTROL_ON if self._gate.os_control() else OS_CONTROL_OFF
        return f"{AGENT_RULES}\n\n{os_control}"

    def specs(self) -> list[ToolSpec]:
        specs = self._gate.registry.specs(
            max_level=Level.DETRUIRE, os_control=self._gate.os_control()
        )
        return [*specs, plan_tool_spec()]

    def describe(self, call: ToolCall) -> str:
        """Ce que fait l'appel, en clair (pour l'interface), sans rien exécuter."""
        if call.name == PLAN_TOOL:
            return "Préparer un plan"
        try:
            tool, args, _ = self._gate.check(call.name, call.arguments)
        except EngineError:
            return call.name
        return tool.describe(args)

    async def handle(
        self,
        call: ToolCall,
        turn: AgentTurn,
        *,
        conversation_id: str | None,
        request: str,
    ) -> CallOutcome:
        if call.name == PLAN_TOOL:
            try:
                plan_in = PlanIn.model_validate(call.arguments)
            except ValidationError as exc:
                first = exc.errors()[0]
                where = ".".join(str(p) for p in first.get("loc", ()))
                return self._failed(call, f"Plan invalide ({where} : {first.get('msg')}).")
            return await self._propose(call, plan_in, turn, conversation_id, request)
        try:
            tool, args, level = self._gate.check(call.name, call.arguments)
        except EngineError as exc:
            return self._failed(call, exc.message)
        if level >= Level.AGIR:
            # Une action n'est jamais exécutée sur un simple appel : elle devient un plan.
            plan_in = PlanIn(
                titre=tool.describe(args)[:120],
                etapes=[
                    StepIn(
                        outil=call.name,
                        arguments=call.arguments,
                        pourquoi="Action demandée pendant la conversation.",
                    )
                ],
            )
            return await self._propose(call, plan_in, turn, conversation_id, request)
        url = call.arguments.get("url")
        if turn.tainted and isinstance(url, str) and not turn.knows(url):
            # Après une lecture externe, une adresse fabriquée (absente de ta demande et de ce
            # qui a été lu) pourrait servir à faire fuir des données : tu valides d'abord.
            plan_in = PlanIn(
                titre=f"Ouvrir {url}"[:120],
                etapes=[
                    StepIn(
                        outil=call.name,
                        arguments=call.arguments,
                        pourquoi=(
                            "Adresse absente de ta demande et des pages lues : elle peut "
                            "venir d'un contenu piégé."
                        ),
                    )
                ],
            )
            return await self._propose(call, plan_in, turn, conversation_id, request)
        return await self._read(
            call,
            tool.describe(args),
            int(level),
            turn,
            conversation_id=conversation_id,
            request=request,
        )

    async def _read(
        self,
        call: ToolCall,
        description: str,
        level: int,
        turn: AgentTurn,
        *,
        conversation_id: str | None,
        request: str,
    ) -> CallOutcome:
        """Outil de niveau 1 : exécuté tout de suite, par la porte des permissions."""
        try:
            output = await self._gate.execute(call.name, call.arguments)
        except EngineError as exc:
            return self._failed(call, exc.message, description)
        except Exception as exc:
            log.exception("tool_failed", tool=call.name)
            return self._failed(call, f"Erreur inattendue ({type(exc).__name__}).", description)
        event = {
            "id": call.id,
            "name": call.name,
            "description": description,
            "level": level,
            "status": "done",
            "source": output.source,
        }
        turn.tools.append(event)
        turn.known_urls |= urls_in(output.text) | urls_in(output.data)
        if output.external:
            turn.tainted = True
        content = as_data(output.text, origin=output.source) if output.external else output.text
        if output.follow_up is None:
            return CallOutcome(content, event)
        # L'outil propose sa suite (ex. activer un skill dont les tests ont réussi) : un plan,
        # au niveau de cette suite, qui attend ta décision.
        follow = output.follow_up
        plan_in = PlanIn(
            titre=follow.why[:120],
            etapes=[StepIn(outil=follow.tool, arguments=follow.arguments, pourquoi=follow.why)],
        )
        proposed = await self._propose(call, plan_in, turn, conversation_id, request)
        return CallOutcome(f"{content}\n\n{proposed.content}", event, plan=proposed.plan)

    async def _propose(
        self,
        call: ToolCall,
        plan_in: PlanIn,
        turn: AgentTurn,
        conversation_id: str | None,
        request: str,
    ) -> CallOutcome:
        try:
            plan = await self._plans.create(
                plan_in, conversation_id=conversation_id, request=request, tainted=turn.tainted
            )
        except EngineError as exc:
            return self._failed(call, f"Plan refusé : {exc.message} Corrige-le.")
        turn.plans.append(plan.id)
        if self._executor is not None and plan.max_level == 1 and not plan.tainted:
            plan = await self._executor.start(plan.id)
            event = {
                "id": call.id,
                "name": PLAN_TOOL,
                "description": f"Plan lancé : {plan.title}",
                "level": plan.max_level,
                "status": "proposed",
                "plan": plan_summary(plan),
            }
            turn.tools.append({k: v for k, v in event.items() if k != "plan"})
            return CallOutcome(PLAN_STARTED, event, plan=plan)
        summary = plan_summary(plan)
        await self._bus.publish(
            "plan.proposed",
            {"id": plan.id, "title": plan.title, "max_level": plan.max_level},
        )
        steps = "\n".join(
            f"{s.position}. {s.description} (niveau {s.level} : {LEVEL_LABELS[Level(s.level)]})"
            for s in plan.steps
        )
        event = {
            "id": call.id,
            "name": PLAN_TOOL,
            "description": f"Plan proposé : {plan.title}",
            "level": plan.max_level,
            "status": "proposed",
            "plan": summary,
        }
        turn.tools.append({k: v for k, v in event.items() if k != "plan"})
        return CallOutcome(f"{PLAN_PENDING}\n\nÉtapes :\n{steps}", event, plan=plan)

    @staticmethod
    def _failed(call: ToolCall, message: str, description: str | None = None) -> CallOutcome:
        event = {
            "id": call.id,
            "name": call.name,
            "description": description or call.name,
            "status": "failed",
            "error": message,
        }
        return CallOutcome(f"Échec : {message}", event, is_error=True)
