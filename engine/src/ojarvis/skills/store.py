"""Les versions des skills, en base : brouillon, testé, actif, désactivé, remplacé."""

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
from ojarvis.db.models import Skill
from ojarvis.skills.models import SkillDefinition, version_key
from ojarvis.skills.runner import TestReport

#: Une version qui a été active ne se réécrit plus : on en crée une plus haute.
FROZEN = frozenset({"actif", "desactive", "remplace"})


@dataclass(frozen=True)
class SkillRecord:
    id: str
    definition: SkillDefinition
    digest: str
    status: str
    report: TestReport | None
    created_by: str
    conversation_id: str | None
    created_at: datetime
    tested_at: datetime | None
    activated_at: datetime | None

    @property
    def name(self) -> str:
        return self.definition.nom

    @property
    def version(self) -> str:
        return self.definition.version

    @property
    def label(self) -> str:
        return f"« {self.name} » v{self.version}"

    @property
    def tested_ok(self) -> bool:
        return self.report is not None and self.report.ok


def _record(row: Skill) -> SkillRecord:
    manifest: dict[str, Any] = row.manifest
    definition = SkillDefinition.model_validate(
        {
            "nom": row.name,
            "version": row.version,
            "description": row.description,
            "instructions": manifest.get("instructions", ""),
            "outils": manifest.get("outils", []),
            "code": row.code,
            "tests": row.tests,
        }
    )
    return SkillRecord(
        id=row.id,
        definition=definition,
        digest=row.digest,
        status=row.status,
        report=TestReport.from_json(row.report) if row.report else None,
        created_by=row.created_by,
        conversation_id=row.conversation_id,
        created_at=row.created_at,
        tested_at=row.tested_at,
        activated_at=row.activated_at,
    )


class SkillStore:
    def __init__(self, db: Database, *, clock: Callable[[], datetime] = utc_now) -> None:
        self._db = db
        self._clock = clock

    async def save_draft(
        self,
        definition: SkillDefinition,
        *,
        created_by: str,
        conversation_id: str | None = None,
    ) -> SkillRecord:
        """Nouvelle version en brouillon ; un brouillon de même version est remplacé."""
        now = self._clock()

        def write(session: Session) -> SkillRecord:
            row = session.scalars(
                select(Skill).where(
                    Skill.name == definition.nom, Skill.version == definition.version
                )
            ).first()
            if row is not None and row.status in FROZEN:
                raise ConflictError(
                    f"La version {definition.version} de « {definition.nom} » a déjà servi : "
                    "choisis une version plus haute."
                )
            if row is None:
                row = Skill(id=uuid.uuid4().hex, created_at=now)
                session.add(row)
            row.name = definition.nom
            row.version = definition.version
            row.description = definition.description
            row.manifest = definition.manifest()
            row.code = definition.code
            row.tests = definition.tests
            row.digest = definition.digest()
            row.status = "brouillon"
            row.report = None
            row.created_by = created_by
            row.conversation_id = conversation_id
            row.created_at = now
            row.tested_at = None
            row.activated_at = None
            session.flush()
            return _record(row)

        return await self._db.run(write)

    async def set_report(self, skill_id: str, report: TestReport) -> SkillRecord:
        now = self._clock()

        def write(session: Session) -> SkillRecord:
            row = self._row(session, skill_id)
            row.report = report.to_json()
            row.tested_at = now
            if row.status not in FROZEN:
                row.status = "pret" if report.ok else "echec"
            return _record(row)

        return await self._db.run(write)

    async def activate(self, skill_id: str) -> tuple[SkillRecord, SkillRecord | None]:
        """Active cette version ; l'ancienne version active du skill est remplacée."""
        now = self._clock()

        def write(session: Session) -> tuple[SkillRecord, SkillRecord | None]:
            row = self._row(session, skill_id)
            report = TestReport.from_json(row.report) if row.report else None
            if report is None or not report.ok:
                raise ConflictError("Ses tests n'ont pas tous réussi : il ne peut pas être activé.")
            if row.status == "actif":
                return _record(row), None
            previous = session.scalars(
                select(Skill).where(Skill.name == row.name, Skill.status == "actif")
            ).first()
            replaced = None
            if previous is not None:
                previous.status = "remplace"
                replaced = _record(previous)
            row.status = "actif"
            row.activated_at = now
            return _record(row), replaced

        return await self._db.run(write)

    async def disable(self, skill_id: str) -> SkillRecord:
        def write(session: Session) -> SkillRecord:
            row = self._row(session, skill_id)
            if row.status != "actif":
                raise ConflictError("Ce skill n'est pas actif.")
            row.status = "desactive"
            return _record(row)

        return await self._db.run(write)

    async def delete(self, skill_id: str) -> SkillRecord:
        def write(session: Session) -> SkillRecord:
            row = self._row(session, skill_id)
            if row.status == "actif":
                raise ConflictError("Désactive ce skill avant de le supprimer.")
            record = _record(row)
            session.delete(row)
            return record

        return await self._db.run(write)

    async def get(self, skill_id: str) -> SkillRecord:
        return await self._db.run(lambda session: _record(self._row(session, skill_id)))

    async def find(self, name: str, version: str) -> SkillRecord | None:
        def read(session: Session) -> SkillRecord | None:
            row = session.scalars(
                select(Skill).where(Skill.name == name, Skill.version == version)
            ).first()
            return _record(row) if row is not None else None

        return await self._db.run(read)

    async def all(self) -> list[SkillRecord]:
        def read(session: Session) -> list[SkillRecord]:
            return [_record(r) for r in session.scalars(select(Skill))]

        records = await self._db.run(read)
        # Par nom, puis de la version la plus récente à la plus ancienne.
        return sorted(records, key=lambda r: (r.name, [-p for p in version_key(r.version)]))

    async def active(self) -> list[SkillRecord]:
        return [r for r in await self.all() if r.status == "actif"]

    @staticmethod
    def _row(session: Session, skill_id: str) -> Skill:
        row = session.get(Skill, skill_id)
        if row is None:
            raise NotFoundError("Skill introuvable.")
        return row
