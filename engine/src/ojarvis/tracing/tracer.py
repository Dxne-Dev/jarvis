"""Traces : chaque requête est suivie, étape par étape (modèle, jetons, coût, latence).

Usage :
    async with tracer.trace("chat", kind="chat") as t:
        async with tracer.span("appel LLM", kind="llm", model="deepseek-flash") as s:
            ...
            s.set(tokens_in=120, tokens_out=48, cost_usd=0.0001)
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ojarvis.core.clock import utc_now
from ojarvis.core.context import correlation_id_var, current_correlation_id, new_correlation_id
from ojarvis.core.logs import get_logger
from ojarvis.db.engine import Database
from ojarvis.db.models import SpanRecord, TraceRecord
from ojarvis.events.bus import EventBus
from ojarvis.security.redaction import REDACTOR

log = get_logger(__name__)


@dataclass
class SpanHandle:
    id: str
    trace_id: str
    parent_id: str | None
    name: str
    kind: str
    started_at: datetime
    attributes: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"
    error: str | None = None

    def set(self, **attributes: Any) -> None:
        self.attributes.update(attributes)

    def fail(self, message: str) -> None:
        self.status = "error"
        self.error = REDACTOR.redact(message)[:500]


@dataclass
class TraceHandle:
    id: str
    name: str
    kind: str
    correlation_id: str
    started_at: datetime
    meta: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"
    error: str | None = None

    def set(self, **meta: Any) -> None:
        self.meta.update(meta)

    def fail(self, message: str) -> None:
        self.status = "error"
        self.error = REDACTOR.redact(message)[:500]


_current_trace: ContextVar[TraceHandle | None] = ContextVar("current_trace", default=None)
_current_span: ContextVar[SpanHandle | None] = ContextVar("current_span", default=None)


def _new_id() -> str:
    return uuid.uuid4().hex


class Tracer:
    def __init__(self, db: Database, bus: EventBus) -> None:
        self._db = db
        self._bus = bus

    @asynccontextmanager
    async def trace(
        self, name: str, *, kind: str = "task", meta: dict[str, Any] | None = None
    ) -> AsyncIterator[TraceHandle]:
        correlation_id = current_correlation_id() or new_correlation_id()
        handle = TraceHandle(
            id=_new_id(),
            name=name,
            kind=kind,
            correlation_id=correlation_id,
            started_at=utc_now(),
            meta=dict(meta or {}),
        )
        cid_token = correlation_id_var.set(correlation_id)
        trace_token = _current_trace.set(handle)
        start = time.perf_counter()
        await self._db.run(lambda s: s.add(self._trace_record(handle, None, None)))
        try:
            yield handle
        except BaseException as exc:
            handle.fail(f"{type(exc).__name__}: {exc}")
            raise
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            ended_at = utc_now()
            await self._db.run(lambda s: s.merge(self._trace_record(handle, ended_at, duration_ms)))
            await self._bus.publish(
                "trace.finished",
                {
                    "trace_id": handle.id,
                    "name": handle.name,
                    "kind": handle.kind,
                    "status": handle.status,
                    "duration_ms": round(duration_ms, 1),
                },
                source="tracing",
                persist=False,
            )
            _current_trace.reset(trace_token)
            correlation_id_var.reset(cid_token)

    @staticmethod
    def _trace_record(
        handle: TraceHandle, ended_at: datetime | None, duration_ms: float | None
    ) -> TraceRecord:
        return TraceRecord(
            id=handle.id,
            correlation_id=handle.correlation_id,
            kind=handle.kind,
            name=handle.name[:200],
            status="running" if ended_at is None else handle.status,
            started_at=handle.started_at,
            ended_at=ended_at,
            duration_ms=duration_ms,
            meta=REDACTOR.redact_obj(handle.meta),
            error=handle.error,
        )

    @asynccontextmanager
    async def span(
        self, name: str, *, kind: str = "step", **attributes: Any
    ) -> AsyncIterator[SpanHandle]:
        trace = _current_trace.get()
        if trace is None:
            # Étape hors trace : on ouvre une trace dédiée pour ne rien perdre.
            async with (
                self.trace(name, kind=kind) as _,
                self.span(name, kind=kind, **attributes) as inner,
            ):
                yield inner
            return
        parent = _current_span.get()
        handle = SpanHandle(
            id=_new_id(),
            trace_id=trace.id,
            parent_id=parent.id if parent else None,
            name=name,
            kind=kind,
            started_at=utc_now(),
            attributes=dict(attributes),
        )
        token = _current_span.set(handle)
        start = time.perf_counter()
        try:
            yield handle
        except BaseException as exc:
            handle.fail(f"{type(exc).__name__}: {exc}")
            raise
        finally:
            _current_span.reset(token)
            duration_ms = (time.perf_counter() - start) * 1000
            record = SpanRecord(
                id=handle.id,
                trace_id=handle.trace_id,
                parent_id=handle.parent_id,
                name=handle.name[:200],
                kind=handle.kind,
                status=handle.status,
                started_at=handle.started_at,
                ended_at=utc_now(),
                duration_ms=duration_ms,
                attributes=REDACTOR.redact_obj(handle.attributes),
                error=handle.error,
            )
            await self._db.run(lambda s: s.add(record))
            await self._bus.publish(
                "trace.span",
                {
                    "trace_id": handle.trace_id,
                    "span_id": handle.id,
                    "name": handle.name,
                    "kind": handle.kind,
                    "status": handle.status,
                    "duration_ms": round(duration_ms, 1),
                },
                source="tracing",
                persist=False,
            )


@dataclass(frozen=True)
class TraceSummary:
    id: str
    name: str
    kind: str
    status: str
    started_at: datetime
    duration_ms: float | None
    correlation_id: str | None
    error: str | None
    span_count: int
    meta: dict[str, Any]


class TraceQueries:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def recent(
        self, *, limit: int = 50, before: datetime | None = None
    ) -> list[TraceSummary]:
        def read(session: Session) -> list[TraceSummary]:
            query = select(TraceRecord).order_by(TraceRecord.started_at.desc()).limit(limit)
            if before is not None:
                query = query.where(TraceRecord.started_at < before)
            traces = list(session.scalars(query))
            counts: dict[str, int] = {}
            if traces:
                ids = [t.id for t in traces]
                for span in session.scalars(select(SpanRecord).where(SpanRecord.trace_id.in_(ids))):
                    counts[span.trace_id] = counts.get(span.trace_id, 0) + 1
            return [
                TraceSummary(
                    id=t.id,
                    name=t.name,
                    kind=t.kind,
                    status=t.status,
                    started_at=t.started_at,
                    duration_ms=t.duration_ms,
                    correlation_id=t.correlation_id,
                    error=t.error,
                    span_count=counts.get(t.id, 0),
                    meta=t.meta,
                )
                for t in traces
            ]

        return await self._db.run(read)

    async def get(self, trace_id: str) -> tuple[TraceRecord, list[SpanRecord]] | None:
        def read(session: Session) -> tuple[TraceRecord, list[SpanRecord]] | None:
            trace = session.get(TraceRecord, trace_id)
            if trace is None:
                return None
            spans = list(
                session.scalars(
                    select(SpanRecord)
                    .where(SpanRecord.trace_id == trace_id)
                    .order_by(SpanRecord.started_at)
                )
            )
            return trace, spans

        return await self._db.run(read)
