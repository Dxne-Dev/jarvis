"""Automatisations en base : création, lecture, modification, suppression, échéances."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, tzinfo
from typing import Any

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from ojarvis.automations.models import (
    Action,
    EventTrigger,
    Instruction,
    Reminder,
    TimeTrigger,
    Trigger,
    describe_action,
    describe_trigger,
    is_one_shot,
)
from ojarvis.automations.schedule import next_run
from ojarvis.core.clock import utc_now
from ojarvis.core.errors import NotFoundError
from ojarvis.db.engine import Database
from ojarvis.db.models import Automation

_TRIGGER: TypeAdapter[TimeTrigger | EventTrigger] = TypeAdapter(Trigger)
_ACTION: TypeAdapter[Reminder | Instruction] = TypeAdapter(Action)


@dataclass(frozen=True)
class AutomationRecord:
    id: str
    name: str
    trigger: TimeTrigger | EventTrigger
    action: Reminder | Instruction
    enabled: bool
    one_shot: bool
    created_by: str
    created_at: datetime
    updated_at: datetime
    next_run_at: datetime | None
    last_run_at: datetime | None
    last_status: str | None
    run_count: int
    conversation_id: str | None

    @property
    def when(self) -> str:
        return describe_trigger(self.trigger)

    @property
    def what(self) -> str:
        return describe_action(self.action)

    def summary(self) -> str:
        return f"« {self.name} » : {self.when} — {self.what}"


def _record(row: Automation) -> AutomationRecord:
    return AutomationRecord(
        id=row.id,
        name=row.name,
        trigger=_TRIGGER.validate_python(row.trigger),
        action=_ACTION.validate_python(row.action),
        enabled=row.enabled,
        one_shot=row.one_shot,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
        next_run_at=row.next_run_at,
        last_run_at=row.last_run_at,
        last_status=row.last_status,
        run_count=row.run_count,
        conversation_id=row.conversation_id,
    )


def _next(trigger: TimeTrigger | EventTrigger, after: datetime, tz: tzinfo) -> datetime | None:
    return next_run(trigger.quand, after, tz) if isinstance(trigger, TimeTrigger) else None


class AutomationStore:
    def __init__(
        self, db: Database, timezone: Any, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._db = db
        self._clock = clock
        #: Fonction qui rend le fuseau du système (relu à chaque calcul : il peut changer).
        self._timezone = timezone
        #: Noms connus, pour décrire une action sans attendre la base (écran de validation).
        self._names: dict[str, str] = {}

    def name_of(self, prefix: str) -> str | None:
        found = [name for key, name in self._names.items() if key.startswith(prefix.strip())]
        return found[0] if len(found) == 1 else None

    async def create(
        self,
        name: str,
        trigger: TimeTrigger | EventTrigger,
        action: Reminder | Instruction,
        *,
        created_by: str,
    ) -> AutomationRecord:
        now = self._clock()
        row = Automation(
            id=uuid.uuid4().hex,
            name=name.strip()[:120],
            trigger=trigger.model_dump(),
            action=action.model_dump(),
            enabled=True,
            one_shot=is_one_shot(trigger),
            created_by=created_by,
            created_at=now,
            updated_at=now,
            next_run_at=_next(trigger, now, self._timezone()),
            last_run_at=None,
            last_status=None,
            run_count=0,
            conversation_id=None,
        )

        def write(session: Session) -> AutomationRecord:
            session.add(row)
            session.flush()
            return _record(row)

        record = await self._db.run(write)
        self._names[record.id] = record.name
        return record

    async def get(self, automation_id: str) -> AutomationRecord:
        def read(session: Session) -> AutomationRecord:
            row = session.get(Automation, automation_id)
            if row is None:
                raise NotFoundError("Automatisation introuvable.")
            return _record(row)

        return await self._db.run(read)

    async def all(self) -> list[AutomationRecord]:
        def read(session: Session) -> list[AutomationRecord]:
            rows = session.scalars(select(Automation).order_by(Automation.created_at.desc()))
            return [_record(r) for r in rows]

        records = await self._db.run(read)
        self._names = {r.id: r.name for r in records}
        return records

    async def update(
        self,
        automation_id: str,
        *,
        name: str | None = None,
        trigger: TimeTrigger | EventTrigger | None = None,
        action: Reminder | Instruction | None = None,
        enabled: bool | None = None,
    ) -> AutomationRecord:
        now = self._clock()
        tz = self._timezone()

        def write(session: Session) -> AutomationRecord:
            row = session.get(Automation, automation_id)
            if row is None:
                raise NotFoundError("Automatisation introuvable.")
            if name is not None:
                row.name = name.strip()[:120]
            if action is not None:
                row.action = action.model_dump()
            if trigger is not None:
                row.trigger = trigger.model_dump()
                row.one_shot = is_one_shot(trigger)
            if enabled is not None:
                row.enabled = enabled
            if trigger is not None or enabled:
                # Nouvel horaire, ou réactivation : la prochaine échéance repart de maintenant.
                row.next_run_at = _next(_TRIGGER.validate_python(row.trigger), now, tz)
            row.updated_at = now
            return _record(row)

        record = await self._db.run(write)
        self._names[record.id] = record.name
        return record

    async def delete(self, automation_id: str) -> AutomationRecord:
        def write(session: Session) -> AutomationRecord:
            row = session.get(Automation, automation_id)
            if row is None:
                raise NotFoundError("Automatisation introuvable.")
            record = _record(row)
            session.delete(row)
            return record

        record = await self._db.run(write)
        self._names.pop(record.id, None)
        return record

    async def due(self, now: datetime) -> list[AutomationRecord]:
        def read(session: Session) -> list[AutomationRecord]:
            rows = session.scalars(
                select(Automation)
                .where(
                    Automation.enabled.is_(True),
                    Automation.next_run_at.is_not(None),
                    Automation.next_run_at <= now,
                )
                .order_by(Automation.next_run_at)
            )
            return [_record(r) for r in rows]

        return await self._db.run(read)

    async def next_due(self) -> datetime | None:
        def read(session: Session) -> datetime | None:
            return session.scalar(
                select(Automation.next_run_at)
                .where(Automation.enabled.is_(True), Automation.next_run_at.is_not(None))
                .order_by(Automation.next_run_at)
                .limit(1)
            )

        return await self._db.run(read)

    async def mark(
        self,
        automation_id: str,
        *,
        at: datetime,
        status: str,
        ran: bool,
        reschedule: bool = True,
    ) -> AutomationRecord:
        """Après un passage (ou un passage manqué) : prochaine échéance, ponctuelle éteinte.

        Un lancement à la main (`reschedule=False`) ne change ni l'horaire ni l'état."""
        tz = self._timezone()

        def write(session: Session) -> AutomationRecord:
            row = session.get(Automation, automation_id)
            if row is None:
                raise NotFoundError("Automatisation introuvable.")
            trigger = _TRIGGER.validate_python(row.trigger)
            if ran:
                row.last_run_at = at
                row.run_count += 1
            row.last_status = status
            if reschedule:
                row.next_run_at = _next(trigger, at, tz)
                if row.one_shot:
                    row.enabled = False
                    row.next_run_at = None
            row.updated_at = self._clock()
            return _record(row)

        return await self._db.run(write)

    async def set_conversation(self, automation_id: str, conversation_id: str) -> None:
        def write(session: Session) -> None:
            row = session.get(Automation, automation_id)
            if row is not None:
                row.conversation_id = conversation_id

        await self._db.run(write)

    async def set_status(self, automation_id: str, status: str) -> None:
        def write(session: Session) -> None:
            row = session.get(Automation, automation_id)
            if row is not None:
                row.last_status = status

        await self._db.run(write)
