"""Déléguer à un agent : Jarvis confie une tâche autonome à l'agent dev, recherche ou coach.

Niveau 1 : l'agent lit seul et propose des plans pour agir ; il ne fait rien de plus que ce
que la porte des permissions permet. Son compte rendu revient à Jarvis comme une donnée
s'il a lu du contenu extérieur.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import Field

from ojarvis.agents.orchestrator import Orchestrator
from ojarvis.core.errors import UpstreamError
from ojarvis.tools.base import Level, Tool, ToolArgs, ToolContext, ToolOutput


class DelegateArgs(ToolArgs):
    agent: Literal["dev", "recherche", "coach"] = Field(
        description="dev (code, fichiers, GitHub), recherche (web, sources), coach (apprendre).",
    )
    tache: str = Field(
        min_length=5,
        max_length=2000,
        description="La tâche, complète : l'agent ne voit pas la conversation.",
    )


class Delegate(Tool[DelegateArgs]):
    name: ClassVar[str] = "deleguer"
    description: ClassVar[str] = (
        "Confie une tâche autonome à un agent spécialisé (dev, recherche, coach) et rend son "
        "compte rendu. Pour une recherche en plusieurs sources, du code, un apprentissage."
    )
    Args: ClassVar[type[ToolArgs]] = DelegateArgs
    level: ClassVar[Level] = Level.LIRE

    def __init__(self, orchestrator: Orchestrator) -> None:
        self._orchestrator = orchestrator

    def describe(self, args: DelegateArgs) -> str:
        label = self._orchestrator.agent(args.agent).label
        task = args.tache if len(args.tache) <= 90 else args.tache[:89] + "…"
        return f"Confier à l'agent {label} : « {task} »"

    async def run(self, args: DelegateArgs, ctx: ToolContext) -> ToolOutput:
        del ctx
        run = await self._orchestrator.delegate(args.agent, args.tache, origin="chat")
        label = self._orchestrator.agent(args.agent).label
        if run.status != "fini":
            raise UpstreamError(f"L'agent {label} n'a pas fini : {run.error or run.status}.")
        lines = [f"Compte rendu de l'agent {label} :", run.result or "(vide)"]
        if run.plans:
            lines.append(f"{len(run.plans)} plan(s) proposé(s) : ils attendent la validation.")
        return ToolOutput(
            "\n".join(lines),
            {"mission": run.id, "plans": run.plans},
            external=run.external,
            source=f"agent {label}",
        )


def agent_tools(orchestrator: Orchestrator) -> list[Tool[Any]]:
    return [Delegate(orchestrator)]
