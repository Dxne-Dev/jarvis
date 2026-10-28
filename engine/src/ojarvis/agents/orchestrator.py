"""L'orchestrateur : il confie une tâche à l'agent nommé, suit la mission et la rapporte.

Aucune logique métier ici : il ne choisit pas l'agent (Jarvis ou toi le nommez), ne découpe
pas la tâche et ne lit pas le résultat. Il lance, publie l'état en direct (événements
`agent.*`), enregistre la mission et rend le compte rendu. Un agent fait une mission à la fois.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ojarvis.agents.base import AgentOutcome, AgentStep, BaseAgent, MissionBudget
from ojarvis.core.clock import utc_now
from ojarvis.core.errors import ConflictError, NotFoundError
from ojarvis.core.logs import get_logger
from ojarvis.db.engine import Database
from ojarvis.db.models import AgentRunRecord
from ojarvis.events.bus import EventBus
from ojarvis.notifications import Notice, Notifier
from ojarvis.tracing.tracer import Tracer

log = get_logger(__name__)


@dataclass(frozen=True)
class AgentRun:
    id: str
    agent: str
    task: str
    status: str
    origin: str
    result: str | None
    error: str | None
    steps: list[dict[str, Any]]
    plans: list[str]
    #: L'agent a lu du contenu extérieur : son compte rendu est une donnée.
    external: bool
    trace_id: str | None
    started_at: datetime
    ended_at: datetime | None


def _run(row: AgentRunRecord) -> AgentRun:
    return AgentRun(
        id=row.id,
        agent=row.agent,
        task=row.task,
        status=row.status,
        origin=row.origin,
        result=row.result,
        error=row.error,
        steps=list(row.steps),
        plans=[str(p) for p in row.plans.get("ids", [])],
        external=bool(row.plans.get("external", False)),
        trace_id=row.trace_id,
        started_at=row.started_at,
        ended_at=row.ended_at,
    )


class Orchestrator:
    def __init__(
        self,
        agents: Mapping[str, BaseAgent],
        *,
        db: Database,
        bus: EventBus,
        tracer: Tracer,
        notifier: Notifier | None = None,
    ) -> None:
        self.agents = dict(agents)
        self._db = db
        self._bus = bus
        self._tracer = tracer
        self._notifier = notifier
        #: Agent occupé → mission en cours.
        self._busy: dict[str, str] = {}
        self._tasks: set[asyncio.Task[AgentRun]] = set()

    async def recover(self) -> None:
        """Une mission coupée par un arrêt du moteur n'est jamais relancée : elle est notée."""

        def write(session: Session) -> int:
            rows = list(
                session.scalars(select(AgentRunRecord).where(AgentRunRecord.status == "en_cours"))
            )
            for row in rows:
                row.status = "interrompu"
                row.error = "Jarvis s'est arrêté pendant la mission."
                row.ended_at = utc_now()
            return len(rows)

        if count := await self._db.run(write):
            log.info("agent_runs_interrupted", count=count)

    def status(self) -> list[dict[str, Any]]:
        return [
            {
                "name": agent.name,
                "label": agent.label,
                "goal": agent.goal,
                "tools": list(agent.tools),
                "busy": agent.name in self._busy,
                "run": self._busy.get(agent.name),
            }
            for agent in self.agents.values()
        ]

    def agent(self, name: str) -> BaseAgent:
        agent = self.agents.get(name)
        if agent is None:
            raise NotFoundError(f"Agent inconnu : {name}.")
        return agent

    async def delegate(
        self,
        name: str,
        task: str,
        *,
        origin: str = "chat",
        conversation_id: str | None = None,
        budget: MissionBudget | None = None,
    ) -> AgentRun:
        """Confie la tâche et attend le compte rendu."""
        run = await self._open(name, task, origin)
        return await self._execute(run, conversation_id, budget)

    async def launch(
        self,
        name: str,
        task: str,
        *,
        origin: str = "interface",
        budget: MissionBudget | None = None,
    ) -> AgentRun:
        """Confie la tâche en arrière-plan ; l'état arrive par les événements `agent.*`."""
        run = await self._open(name, task, origin)
        job = asyncio.create_task(self._execute(run, None, budget))
        self._tasks.add(job)
        job.add_done_callback(self._tasks.discard)
        return run

    async def runs(self, *, limit: int = 30, agent: str | None = None) -> list[AgentRun]:
        def read(session: Session) -> list[AgentRun]:
            query = select(AgentRunRecord).order_by(AgentRunRecord.started_at.desc()).limit(limit)
            if agent is not None:
                query = query.where(AgentRunRecord.agent == agent)
            return [_run(r) for r in session.scalars(query)]

        return await self._db.run(read)

    async def get(self, run_id: str) -> AgentRun:
        def read(session: Session) -> AgentRun:
            row = session.get(AgentRunRecord, run_id)
            if row is None:
                raise NotFoundError("Mission introuvable.")
            return _run(row)

        return await self._db.run(read)

    async def close(self) -> None:
        for job in list(self._tasks):
            job.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    # ------------------------------------------------------------------ interne

    async def _open(self, name: str, task: str, origin: str) -> AgentRun:
        agent = self.agent(name)
        if name in self._busy:
            raise ConflictError(f"L'agent {agent.label} est déjà en mission : attends sa fin.")
        row = AgentRunRecord(
            id=uuid.uuid4().hex,
            agent=name,
            task=task.strip()[:4000],
            status="en_cours",
            origin=origin,
            result=None,
            error=None,
            steps=[],
            plans={"ids": []},
            trace_id=None,
            started_at=utc_now(),
            ended_at=None,
        )

        def write(session: Session) -> AgentRun:
            session.add(row)
            session.flush()
            return _run(row)

        run = await self._db.run(write)
        self._busy[name] = run.id
        await self._publish("agent.started", run)
        return run

    async def _execute(
        self, run: AgentRun, conversation_id: str | None, budget: MissionBudget | None = None
    ) -> AgentRun:
        agent = self.agent(run.agent)

        async def progress(step: AgentStep) -> None:
            entry = {"tool": step.tool, "description": step.description, "status": step.status}
            if step.error:
                entry["error"] = step.error[:300]
            await self._update(run.id, step=entry)
            await self._bus.publish(
                "agent.step",
                {"run": run.id, "agent": run.agent, **entry},
                source="agents",
            )

        trace_id = None
        outcome: AgentOutcome | None = None
        error = None
        try:
            async with self._tracer.trace(
                f"Agent {agent.label} : {run.task[:60]}", kind="agent", meta={"agent": run.agent}
            ) as trace:
                trace_id = trace.id
                outcome = await agent.run(
                    run.task, conversation_id=conversation_id, progress=progress, budget=budget
                )
        except asyncio.CancelledError:
            error = "Mission arrêtée."
            raise
        except Exception as exc:
            log.warning("agent_run_failed", agent=run.agent, error=type(exc).__name__)
            error = f"{type(exc).__name__} : {exc}"[:500]
        finally:
            self._busy.pop(run.agent, None)
            status = "echec" if outcome is None else "suspendue" if outcome.suspended else "fini"
            done = await self._update(
                run.id,
                status=status,
                result=outcome.report if outcome else None,
                error=error,
                plans=outcome.plans if outcome else [],
                external=outcome.external if outcome else False,
                trace_id=trace_id,
                ended=True,
            )
            await self._publish("agent.finished", done)
            if outcome is not None and outcome.suspended and self._notifier is not None:
                # Une mission suspendue te prévient, dans l'app et sur Telegram.
                await self._notifier.notify(
                    Notice(
                        title=f"Mission suspendue : {agent.label}",
                        body=f"{outcome.suspended}. Tâche : {run.task[:200]}",
                    )
                )
        return done

    async def _update(
        self,
        run_id: str,
        *,
        step: dict[str, Any] | None = None,
        status: str | None = None,
        result: str | None = None,
        error: str | None = None,
        plans: list[str] | None = None,
        external: bool = False,
        trace_id: str | None = None,
        ended: bool = False,
    ) -> AgentRun:
        now = utc_now()

        def write(session: Session) -> AgentRun:
            row = session.get(AgentRunRecord, run_id)
            if row is None:
                raise NotFoundError("Mission introuvable.")
            if step is not None:
                row.steps = [*row.steps, step]
            if status is not None:
                row.status = status
            if result is not None:
                row.result = result
            if error is not None:
                row.error = error
            if plans is not None:
                row.plans = {"ids": plans, "external": external}
            if trace_id is not None:
                row.trace_id = trace_id
            if ended:
                row.ended_at = now
            return _run(row)

        return await self._db.run(write)

    async def _publish(self, event: str, run: AgentRun) -> None:
        await self._bus.publish(
            event,
            {
                "run": run.id,
                "agent": run.agent,
                "task": run.task[:200],
                "status": run.status,
                "plans": run.plans,
            },
            source="agents",
        )
