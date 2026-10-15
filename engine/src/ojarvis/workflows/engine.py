"""Moteur de workflows : des chaînes de tâches persistées, qui reprennent après un arrêt.

Chaque exécution est une ligne en base : ses étapes, l'index de la prochaine à faire et ce
que les étapes précédentes ont produit. Après chaque étape, cet état est enregistré. Après
un plantage ou un redémarrage du PC, l'exécution reprend à l'étape où elle s'était arrêtée
(l'étape interrompue est refaite ; les étapes sont donc prévues pour être rejouées).
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ojarvis.core.clock import utc_now
from ojarvis.core.context import correlation_id_var
from ojarvis.core.errors import EngineError, NotFoundError
from ojarvis.core.logs import get_logger
from ojarvis.db.engine import Database
from ojarvis.db.models import WorkflowRun
from ojarvis.events.bus import EventBus

log = get_logger(__name__)

RunStatus = Literal["pending", "running", "done", "failed"]
MAX_ATTEMPTS = 3
RETRY_DELAY_S = 20.0


@dataclass(frozen=True)
class RunRecord:
    id: str
    kind: str
    automation_id: str | None
    title: str
    status: str
    steps: list[dict[str, Any]]
    position: int
    context: dict[str, Any]
    attempts: int
    error: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    ended_at: datetime | None


def _record(row: WorkflowRun) -> RunRecord:
    return RunRecord(
        row.id,
        row.kind,
        row.automation_id,
        row.title,
        row.status,
        list(row.steps),
        row.position,
        dict(row.context),
        row.attempts,
        row.error,
        row.created_at,
        row.updated_at,
        row.started_at,
        row.ended_at,
    )


#: Une étape reçoit ses paramètres et l'exécution en cours ; elle rend ce qu'elle ajoute
#: au contexte (lu par les étapes suivantes).
StepHandler = Callable[[dict[str, Any], RunRecord], Awaitable[dict[str, Any] | None]]


class WorkflowEngine:
    def __init__(
        self,
        db: Database,
        bus: EventBus,
        handlers: dict[str, StepHandler] | None = None,
        *,
        retry_delay_s: float = RETRY_DELAY_S,
    ) -> None:
        self._db = db
        self._bus = bus
        self.handlers: dict[str, StepHandler] = dict(handlers or {})
        self._retry_delay_s = retry_delay_s
        self._wake = asyncio.Event()
        self._worker: asyncio.Task[None] | None = None
        self._not_before: dict[str, float] = {}
        self.idle = asyncio.Event()

    # ------------------------------------------------------------------ cycle de vie

    async def start(self) -> int:
        """Reprend les exécutions coupées par un arrêt, puis lance le travailleur."""

        def resume(session: Session) -> int:
            result = session.execute(
                update(WorkflowRun)
                .where(WorkflowRun.status == "running")
                .values(status="pending", updated_at=utc_now())
            )
            return int(getattr(result, "rowcount", 0) or 0)

        resumed = await self._db.run(resume)
        if resumed:
            log.info("workflows_resumed", count=resumed)
        self._worker = asyncio.create_task(self._work())
        self._wake.set()
        return resumed

    async def close(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._worker
            self._worker = None

    # ------------------------------------------------------------------ soumission et lecture

    async def submit(
        self,
        *,
        kind: str,
        title: str,
        steps: list[dict[str, Any]],
        context: dict[str, Any] | None = None,
        automation_id: str | None = None,
    ) -> RunRecord:
        unknown = [s.get("type") for s in steps if s.get("type") not in self.handlers]
        if unknown:
            raise ValueError(f"étapes inconnues : {unknown}")
        now = utc_now()
        row = WorkflowRun(
            id=uuid.uuid4().hex,
            kind=kind,
            automation_id=automation_id,
            title=title[:200],
            status="pending",
            steps=steps,
            position=0,
            context=dict(context or {}),
            attempts=0,
            error=None,
            created_at=now,
            updated_at=now,
            started_at=None,
            ended_at=None,
        )

        def write(session: Session) -> RunRecord:
            session.add(row)
            session.flush()
            return _record(row)

        record = await self._db.run(write)
        self.idle.clear()
        self._wake.set()
        return record

    async def get(self, run_id: str) -> RunRecord:
        def read(session: Session) -> RunRecord:
            row = session.get(WorkflowRun, run_id)
            if row is None:
                raise NotFoundError("Exécution introuvable.")
            return _record(row)

        return await self._db.run(read)

    async def runs(
        self, *, automation_id: str | None = None, since: datetime | None = None, limit: int = 50
    ) -> list[RunRecord]:
        def read(session: Session) -> list[RunRecord]:
            query = select(WorkflowRun).order_by(WorkflowRun.created_at.desc()).limit(limit)
            if automation_id is not None:
                query = query.where(WorkflowRun.automation_id == automation_id)
            if since is not None:
                query = query.where(WorkflowRun.created_at >= since)
            return [_record(r) for r in session.scalars(query)]

        return await self._db.run(read)

    # ------------------------------------------------------------------ travailleur

    async def _next_pending(self) -> RunRecord | None:
        now = asyncio.get_running_loop().time()

        def read(session: Session) -> list[RunRecord]:
            rows = session.scalars(
                select(WorkflowRun)
                .where(WorkflowRun.status == "pending")
                .order_by(WorkflowRun.created_at)
                .limit(20)
            )
            return [_record(r) for r in rows]

        for record in await self._db.run(read):
            if self._not_before.get(record.id, 0.0) <= now:
                return record
        return None

    async def _work(self) -> None:
        while True:
            record = await self._next_pending()
            if record is None:
                self.idle.set()
                self._wake.clear()
                # Réveil par une soumission, sinon un tour de garde (nouvel essai en attente).
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), self._retry_delay_s)
                continue
            try:
                await self._run(record)
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover - _run attrape déjà les erreurs d'étape
                log.exception("workflow_crashed", run=record.id)

    async def _set(self, run_id: str, **values: Any) -> None:
        def write(session: Session) -> None:
            row = session.get(WorkflowRun, run_id)
            if row is None:
                return
            for key, value in values.items():
                setattr(row, key, value)
            row.updated_at = utc_now()

        await self._db.run(write)

    async def _run(self, record: RunRecord) -> None:
        # Tout ce que fait l'exécution (événements, logs, traces) porte cet identifiant :
        # le planificateur s'en sert pour éviter les réactions en chaîne.
        correlation_id_var.set(f"wf{record.id[:14]}")
        await self._set(record.id, status="running", started_at=record.started_at or utc_now())
        await self._bus.publish(
            "workflow.started", {"id": record.id, "kind": record.kind, "title": record.title}
        )
        context = dict(record.context)
        for position in range(record.position, len(record.steps)):
            step = record.steps[position]
            handler = self.handlers[str(step["type"])]
            current = _record_with(record, position=position, context=context)
            try:
                added = await handler(step, current)
            except asyncio.CancelledError:
                raise  # arrêt du moteur : l'exécution reprendra à cette étape
            except Exception as exc:
                await self._failed(record, position, context, exc)
                return
            context.update(added or {})
            # L'étape est faite : on l'enregistre avant de passer à la suivante.
            await self._set(record.id, position=position + 1, context=context)
        await self._set(record.id, status="done", ended_at=utc_now(), error=None)
        await self._bus.publish(
            "workflow.finished",
            {
                "id": record.id,
                "kind": record.kind,
                "status": "done",
                "automation": record.automation_id,
            },
        )

    async def _failed(
        self, record: RunRecord, position: int, context: dict[str, Any], exc: Exception
    ) -> None:
        message = exc.message if isinstance(exc, EngineError) else f"{type(exc).__name__}: {exc}"
        attempts = record.attempts + 1
        log.warning("workflow_step_failed", run=record.id, step=position, attempts=attempts)
        if attempts < MAX_ATTEMPTS:
            self._not_before[record.id] = asyncio.get_running_loop().time() + self._retry_delay_s
            await self._set(
                record.id,
                status="pending",
                position=position,
                context=context,
                attempts=attempts,
                error=message[:500],
            )
            return
        await self._set(
            record.id,
            status="failed",
            position=position,
            context=context,
            attempts=attempts,
            error=message[:500],
            ended_at=utc_now(),
        )
        await self._bus.publish(
            "workflow.finished",
            {
                "id": record.id,
                "kind": record.kind,
                "status": "failed",
                "automation": record.automation_id,
                "error": message[:200],
            },
        )

    async def wait_idle(self, timeout_s: float = 10.0) -> None:
        """Attend que plus rien ne soit en cours (tests)."""
        await asyncio.wait_for(self.idle.wait(), timeout_s)


def _record_with(record: RunRecord, *, position: int, context: dict[str, Any]) -> RunRecord:
    return RunRecord(
        record.id,
        record.kind,
        record.automation_id,
        record.title,
        "running",
        record.steps,
        position,
        dict(context),
        record.attempts,
        record.error,
        record.created_at,
        record.updated_at,
        record.started_at,
        record.ended_at,
    )
