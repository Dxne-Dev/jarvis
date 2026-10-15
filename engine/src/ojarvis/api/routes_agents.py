"""Agents : qui ils sont, ce qu'ils font en ce moment, leurs missions, et t'en confier une.

L'état en direct arrive par les événements `agent.started`, `agent.step` et `agent.finished`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from ojarvis.agents.orchestrator import AgentRun
from ojarvis.api.deps import ServicesDep

router = APIRouter(prefix="/v1/agents")


class AgentOut(BaseModel):
    name: str
    label: str
    goal: str
    tools: list[str]
    busy: bool
    run: str | None


class AgentRunOut(BaseModel):
    id: str
    agent: str
    task: str
    status: str
    origin: str
    result: str | None
    error: str | None
    steps: list[dict[str, Any]]
    plans: list[str]
    trace_id: str | None
    started_at: datetime
    ended_at: datetime | None


class MissionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str = Field(min_length=5, max_length=2000)


def _run(run: AgentRun) -> AgentRunOut:
    return AgentRunOut(
        id=run.id,
        agent=run.agent,
        task=run.task,
        status=run.status,
        origin=run.origin,
        result=run.result,
        error=run.error,
        steps=run.steps,
        plans=run.plans,
        trace_id=run.trace_id,
        started_at=run.started_at,
        ended_at=run.ended_at,
    )


@router.get("")
async def list_agents(services: ServicesDep) -> list[AgentOut]:
    return [AgentOut.model_validate(a) for a in services.orchestrator.status()]


@router.get("/runs")
async def list_runs(
    services: ServicesDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    agent: str | None = None,
) -> list[AgentRunOut]:
    return [_run(r) for r in await services.orchestrator.runs(limit=limit, agent=agent)]


@router.get("/runs/{run_id}")
async def get_run(run_id: str, services: ServicesDep) -> AgentRunOut:
    return _run(await services.orchestrator.get(run_id))


@router.post("/{name}/runs", status_code=202)
async def start_mission(name: str, body: MissionIn, services: ServicesDep) -> AgentRunOut:
    """Tu confies directement une tâche à un agent ; elle tourne en arrière-plan."""
    return _run(await services.orchestrator.launch(name, body.task, origin="interface"))
