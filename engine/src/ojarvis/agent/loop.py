"""Ce que Jarvis fait d'un appel d'outil pendant une conversation.

- Outil de niveau 1 (lire) : exécuté tout de suite, par la porte des permissions ; son
  résultat revient au modèle encadré comme une donnée s'il vient de l'extérieur.
- `proposer_un_plan` : le plan est vérifié, enregistré, et attend ta décision.
- Appel direct d'une action (niveau 2 ou 3) : jamais exécuté ; il devient un plan
  d'une étape, à valider comme les autres.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

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
    "Tu as des outils. Niveau 1 (lire : recherche web, pages, fichiers, navigateur, code "
    "isolé) : utilise-les directement quand ils aident, sans demander. Niveaux 2 et 3 "
    "(agir : cliquer, remplir, écrire un fichier, utiliser une session ; détruire) : ne les "
    "appelle jamais seuls ; propose un plan avec proposer_un_plan, que l'utilisateur "
    "validera. Pour une tâche en plusieurs étapes, propose tout le plan d'un coup, avec "
    "des cibles précises (adresse, fichier, bouton). N'invente jamais le résultat d'un "
    "outil. Cite tes sources quand tu t'appuies sur le web.\n\n" + DATA_RULE
)
PLAN_PENDING = (
    "Plan enregistré. L'utilisateur le voit à l'écran avec « Valider » et « Refuser » ; rien "
    "n'est exécuté avant sa décision. N'appelle pas d'autre outil : dis-lui en une ou deux "
    "phrases ce que fera le plan et qu'il attend sa validation."
)


@dataclass
class AgentTurn:
    """Ce qui s'est passé pendant un tour : outils utilisés, plans proposés."""

    #: Un contenu externe a été lu : un plan proposé ensuite est signalé à la validation.
    tainted: bool = False
    tools: list[dict[str, Any]] = field(default_factory=list)
    plans: list[str] = field(default_factory=list)


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
    def __init__(self, *, gate: PermissionGate, plans: PlanStore, bus: EventBus) -> None:
        self._gate = gate
        self._plans = plans
        self._bus = bus

    def specs(self) -> list[ToolSpec]:
        return [*self._gate.registry.specs(max_level=Level.DETRUIRE), plan_tool_spec()]

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
        return await self._read(call, tool.describe(args), int(level), turn)

    async def _read(
        self, call: ToolCall, description: str, level: int, turn: AgentTurn
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
        if output.external:
            turn.tainted = True
            return CallOutcome(as_data(output.text, origin=output.source), event)
        return CallOutcome(output.text, event)

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
