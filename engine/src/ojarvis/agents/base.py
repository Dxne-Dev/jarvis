"""Le socle commun des agents : un objectif, des outils et un contexte propres.

Un agent ne voit pas ta conversation : seulement la tâche qu'on lui confie. Il n'utilise que
ses outils, toujours par la porte des permissions : il lit seul ; une action devient un plan
qui attend ta validation, comme pour Jarvis lui-même. Il rend un compte rendu.
"""

from __future__ import annotations

from abc import ABC
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import ClassVar

from pydantic import ValidationError

from ojarvis.agent.loop import Agent, AgentTurn, urls_in
from ojarvis.agent.plans import PLAN_TOOL, PlanIn
from ojarvis.context.engine import PERSONA
from ojarvis.llm.router import ModelRouter
from ojarvis.llm.types import LLMRequest, Message, ToolCall, ToolSpec
from ojarvis.tools.guards import DATA_RULE

MAX_REPORT = 6_000


@dataclass(frozen=True)
class AgentStep:
    tool: str
    description: str
    status: str  # done | failed | proposed
    error: str | None = None


@dataclass
class AgentOutcome:
    report: str
    steps: list[AgentStep] = field(default_factory=list)
    plans: list[str] = field(default_factory=list)
    #: L'agent a lu un contenu extérieur : son compte rendu est une donnée, pas une consigne.
    external: bool = False


Progress = Callable[[AgentStep], Awaitable[None]]


class BaseAgent(ABC):
    """Tous les agents en héritent ; seuls changent l'objectif, les outils et les limites."""

    name: ClassVar[str]
    label: ClassVar[str]
    goal: ClassVar[str]
    tools: ClassVar[tuple[str, ...]]
    max_steps: ClassVar[int] = 6

    def __init__(self, *, router: ModelRouter, core: Agent) -> None:
        self._router = router
        self._core = core

    def instructions(self) -> str:
        return (
            f"{PERSONA}\n\nTu es l'agent « {self.label} » de Jarvis. Ton objectif : {self.goal}\n\n"
            "Tu travailles seul sur la tâche confiée, avec tes seuls outils. Lire : fais-le "
            "directement. Agir (écrire, envoyer, créer) : jamais seul, propose un plan que "
            "l'utilisateur validera. Quand tu as fini, rends un compte rendu bref et précis, en "
            f"français, avec tes sources s'il y en a.\n\n{DATA_RULE}"
        )

    def specs(self) -> list[ToolSpec]:
        allowed = {*self.tools, PLAN_TOOL}
        return [s for s in self._core.specs() if s.name in allowed]

    def _outside(self, call: ToolCall) -> str | None:
        """Un outil, ou une étape de plan, hors de ses attributions."""
        if call.name == PLAN_TOOL:
            try:
                plan = PlanIn.model_validate(call.arguments)
            except ValidationError:
                return None  # la porte expliquera l'erreur
            stray = [s.outil for s in plan.etapes if s.outil not in self.tools]
            return stray[0] if stray else None
        return None if call.name in self.tools else call.name

    async def run(
        self, task: str, *, conversation_id: str | None = None, progress: Progress | None = None
    ) -> AgentOutcome:
        messages = [Message("system", self.instructions()), Message("user", task)]
        turn = AgentTurn()
        turn.known_urls |= urls_in(task)
        outcome = AgentOutcome(report="")
        for _ in range(self.max_steps):
            result = await self._router.complete(
                "chat", LLMRequest(messages=list(messages), tools=self.specs())
            )
            if not result.tool_calls:
                outcome.report = result.text.strip()[:MAX_REPORT]
                break
            messages.append(result.as_message())
            for call in result.tool_calls:
                stray = self._outside(call)
                if stray is not None:
                    step = AgentStep(
                        call.name, call.name, "failed", f"{stray} : hors de mes outils"
                    )
                    content, is_error = f"Échec : l'outil {stray} n'est pas dans tes outils.", True
                else:
                    done = await self._core.handle(
                        call, turn, conversation_id=conversation_id, request=task
                    )
                    event = done.event
                    step = AgentStep(
                        call.name,
                        str(event.get("description") or call.name),
                        str(event.get("status") or "done"),
                        event.get("error"),
                    )
                    content, is_error = done.content, done.is_error
                outcome.steps.append(step)
                if progress is not None:
                    await progress(step)
                messages.append(Message("tool", content, tool_call_id=call.id, is_error=is_error))
        else:
            # Nombre d'étapes atteint : il rend ce qu'il a, sans nouvel outil.
            messages.append(
                Message("user", "Tu as atteint ton nombre d'étapes : rends ton compte rendu.")
            )
            result = await self._router.complete("chat", LLMRequest(messages=messages))
            outcome.report = result.text.strip()[:MAX_REPORT]
        outcome.plans = list(turn.plans)
        outcome.external = turn.tainted
        return outcome
