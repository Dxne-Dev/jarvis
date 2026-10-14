"""Écriture et lecture des événements en base."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ojarvis.db.engine import Database
from ojarvis.db.models import EventRecord
from ojarvis.events.bus import Event


class EventStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def persist(self, event: Event) -> int:
        def write(session: Session) -> int:
            record = EventRecord(
                ts=event.ts,
                type=event.type,
                source=event.source,
                correlation_id=event.correlation_id,
                payload=event.payload,
            )
            session.add(record)
            session.flush()
            return record.id

        return await self._db.run(write)

    async def recent(self, *, limit: int = 100, type_prefix: str | None = None) -> list[Event]:
        def read(session: Session) -> list[Event]:
            query = select(EventRecord).order_by(EventRecord.id.desc()).limit(limit)
            if type_prefix:
                query = query.where(EventRecord.type.startswith(type_prefix))
            return [
                Event(
                    id=r.id,
                    type=r.type,
                    ts=r.ts,
                    source=r.source,
                    correlation_id=r.correlation_id,
                    payload=r.payload,
                )
                for r in session.scalars(query)
            ]

        return await self._db.run(read)
