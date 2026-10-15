"""Journal des actions de niveau 2 et 3 : ajout seul, chaîné par SHA-256, vérifié au démarrage.

Chaque entrée contient l'empreinte de la précédente. Modifier une ligne (même directement
dans la base) casse la chaîne à partir de là, et la vérification le voit. En plus, deux
déclencheurs SQLite refusent toute modification et toute suppression.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ojarvis.core.clock import utc_now
from ojarvis.core.logs import get_logger
from ojarvis.db.engine import Database
from ojarvis.db.models import AuditEntry
from ojarvis.events.bus import EventBus
from ojarvis.security.redaction import REDACTOR

log = get_logger(__name__)

GENESIS = "0" * 64
Actor = Literal["utilisateur", "jarvis", "automatisation"]


@dataclass(frozen=True)
class AuditRecord:
    id: int
    ts: datetime
    actor: str
    action: str
    level: int
    summary: str
    details: dict[str, Any]
    prev_hash: str
    hash: str


@dataclass(frozen=True)
class IntegrityReport:
    ok: bool
    count: int
    #: Première entrée dont l'empreinte ne correspond plus (None si la chaîne est intègre).
    broken_at: int | None = None


def _timestamp(ts: datetime) -> str:
    return ts.astimezone(UTC).isoformat(timespec="microseconds")


def digest(
    prev_hash: str,
    *,
    ts: datetime,
    actor: str,
    action: str,
    level: int,
    summary: str,
    details: dict[str, Any],
) -> str:
    payload = {
        "prev": prev_hash,
        "ts": _timestamp(ts),
        "actor": actor,
        "action": action,
        "level": level,
        "summary": summary,
        "details": details,
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _record(row: AuditEntry) -> AuditRecord:
    return AuditRecord(
        row.id,
        row.ts,
        row.actor,
        row.action,
        row.level,
        row.summary,
        dict(row.details),
        row.prev_hash,
        row.hash,
    )


class AuditJournal:
    def __init__(self, db: Database, bus: EventBus | None = None) -> None:
        self._db = db
        self._bus = bus
        self._lock = asyncio.Lock()
        self.integrity: IntegrityReport | None = None

    async def append(
        self,
        *,
        actor: Actor,
        action: str,
        level: int,
        summary: str,
        details: dict[str, Any] | None = None,
    ) -> AuditRecord:
        # Les secrets connus sont masqués avant l'empreinte : le journal n'en contient jamais.
        clean_summary = REDACTOR.redact(summary)[:500]
        clean_details: dict[str, Any] = REDACTOR.redact_obj(dict(details or {}))
        ts = utc_now()

        def write(session: Session) -> AuditRecord:
            last = session.scalar(select(AuditEntry).order_by(AuditEntry.id.desc()).limit(1))
            prev = last.hash if last is not None else GENESIS
            entry = AuditEntry(
                ts=ts,
                actor=actor,
                action=action,
                level=level,
                summary=clean_summary,
                details=clean_details,
                prev_hash=prev,
                hash=digest(
                    prev,
                    ts=ts,
                    actor=actor,
                    action=action,
                    level=level,
                    summary=clean_summary,
                    details=clean_details,
                ),
            )
            session.add(entry)
            session.flush()
            return _record(entry)

        async with self._lock:
            record = await self._db.run(write)
        if self._bus is not None:
            await self._bus.publish(
                "audit.appended",
                {"id": record.id, "action": action, "level": level, "summary": clean_summary},
                persist=False,
            )
        return record

    async def verify(self) -> IntegrityReport:
        """Recalcule toute la chaîne. Une seule ligne modifiée suffit à la faire échouer."""

        def check(session: Session) -> IntegrityReport:
            prev = GENESIS
            count = 0
            for row in session.scalars(select(AuditEntry).order_by(AuditEntry.id)):
                count += 1
                expected = digest(
                    prev,
                    ts=row.ts,
                    actor=row.actor,
                    action=row.action,
                    level=row.level,
                    summary=row.summary,
                    details=dict(row.details),
                )
                if row.prev_hash != prev or row.hash != expected:
                    return IntegrityReport(False, count, broken_at=row.id)
                prev = row.hash
            return IntegrityReport(True, count)

        report = await self._db.run(check)
        self.integrity = report
        if not report.ok:
            log.error("audit_integrity_failed", broken_at=report.broken_at)
            if self._bus is not None:
                await self._bus.publish(
                    "audit.integrity_failed", {"broken_at": report.broken_at, "count": report.count}
                )
        return report

    async def recent(self, *, limit: int = 100, offset: int = 0) -> tuple[list[AuditRecord], int]:
        def read(session: Session) -> tuple[list[AuditRecord], int]:
            total = session.scalar(select(func.count()).select_from(AuditEntry)) or 0
            rows = session.scalars(
                select(AuditEntry).order_by(AuditEntry.id.desc()).limit(limit).offset(offset)
            )
            return [_record(r) for r in rows], int(total)

        return await self._db.run(read)
