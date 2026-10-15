"""Les suggestions de Jarvis : proposées une seule fois par raison, acceptées ou écartées."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ojarvis.core.clock import utc_now
from ojarvis.core.errors import ConflictError, NotFoundError
from ojarvis.db.engine import Database
from ojarvis.db.models import SuggestionRecord
from ojarvis.events.bus import EventBus


@dataclass(frozen=True)
class Option:
    id: str
    label: str
    #: Ce que Jarvis fera si tu choisis cette option (un message, dans une conversation).
    prompt: str


@dataclass(frozen=True)
class Suggestion:
    id: str
    kind: str
    title: str
    detail: str | None
    options: list[Option]
    confidence: float
    status: str
    conversation_id: str | None
    created_at: datetime
    decided_at: datetime | None


def _suggestion(row: SuggestionRecord) -> Suggestion:
    return Suggestion(
        id=row.id,
        kind=row.kind,
        title=row.title,
        detail=row.detail,
        options=[Option(str(o["id"]), str(o["label"]), str(o["prompt"])) for o in row.options],
        confidence=row.confidence,
        status=row.status,
        conversation_id=row.conversation_id,
        created_at=row.created_at,
        decided_at=row.decided_at,
    )


class SuggestionStore:
    def __init__(
        self, db: Database, bus: EventBus, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._db = db
        self._bus = bus
        self._clock = clock

    async def propose(
        self,
        *,
        kind: str,
        title: str,
        detail: str | None,
        options: list[Option],
        confidence: float,
        fingerprint: str,
    ) -> Suggestion | None:
        """Nouvelle suggestion ; rien si la même raison a déjà donné une suggestion."""
        now = self._clock()

        def write(session: Session) -> Suggestion | None:
            exists = session.scalars(
                select(SuggestionRecord).where(SuggestionRecord.fingerprint == fingerprint[:200])
            ).first()
            if exists is not None:
                return None
            row = SuggestionRecord(
                id=uuid.uuid4().hex,
                kind=kind,
                title=title[:300],
                detail=detail[:500] if detail else None,
                options=[{"id": o.id, "label": o.label, "prompt": o.prompt} for o in options],
                confidence=round(max(0.0, min(confidence, 1.0)), 2),
                fingerprint=fingerprint[:200],
                status="nouvelle",
                conversation_id=None,
                created_at=now,
                decided_at=None,
            )
            session.add(row)
            session.flush()
            return _suggestion(row)

        suggestion = await self._db.run(write)
        if suggestion is not None:
            await self._bus.publish(
                "suggestion.created",
                {
                    "id": suggestion.id,
                    "kind": suggestion.kind,
                    "title": suggestion.title,
                    "confidence": suggestion.confidence,
                },
                source="anticipation",
            )
        return suggestion

    async def pending(self) -> list[Suggestion]:
        def read(session: Session) -> list[Suggestion]:
            rows = session.scalars(
                select(SuggestionRecord)
                .where(SuggestionRecord.status == "nouvelle")
                .order_by(SuggestionRecord.confidence.desc(), SuggestionRecord.created_at.desc())
            )
            return [_suggestion(r) for r in rows]

        return await self._db.run(read)

    async def get(self, suggestion_id: str) -> Suggestion:
        def read(session: Session) -> Suggestion:
            row = session.get(SuggestionRecord, suggestion_id)
            if row is None:
                raise NotFoundError("Suggestion introuvable.")
            return _suggestion(row)

        return await self._db.run(read)

    async def decide(
        self, suggestion_id: str, status: str, *, conversation_id: str | None = None
    ) -> Suggestion:
        now = self._clock()

        def write(session: Session) -> Suggestion:
            row = session.get(SuggestionRecord, suggestion_id)
            if row is None:
                raise NotFoundError("Suggestion introuvable.")
            if row.status != "nouvelle":
                raise ConflictError("Cette suggestion a déjà été traitée.")
            row.status = status
            row.decided_at = now
            row.conversation_id = conversation_id
            return _suggestion(row)

        suggestion = await self._db.run(write)
        payload: dict[str, Any] = {"id": suggestion.id, "status": status}
        await self._bus.publish("suggestion.updated", payload, source="anticipation")
        return suggestion
