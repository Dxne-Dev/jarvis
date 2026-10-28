"""Plans proposés par Jarvis : chaque étape est vérifiée, décrite et attend ta validation.

Le modèle propose un plan avec l'outil `proposer_un_plan`. Une étape peut reprendre le
résultat d'une étape précédente avec `{{etape N}}` (dans un argument texte).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ojarvis.core.clock import utc_now
from ojarvis.core.errors import InvalidInputError, NotFoundError
from ojarvis.db.engine import Database
from ojarvis.db.models import Plan, PlanStep
from ojarvis.llm.types import ToolSpec
from ojarvis.permissions.gate import PermissionGate
from ojarvis.tools.base import Level

PLAN_TOOL = "proposer_un_plan"
PLACEHOLDER = re.compile(r"\{\{\s*etape\s+(\d+)\s*\}\}")
MAX_STEPS = 8

PlanStatus = Literal["proposed", "approved", "running", "done", "failed", "refused"]
StepStatus = Literal["pending", "running", "done", "failed", "skipped"]


class StepIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outil: str = Field(min_length=1, max_length=64, description="Nom de l'outil.")
    arguments: dict[str, Any] = Field(description="Arguments de l'outil.")
    pourquoi: str = Field(min_length=1, max_length=300, description="Pourquoi cette étape.")


class MeasureIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    commande: str = Field(
        min_length=1,
        max_length=1000,
        description="Une lecture qui mesure le résultat attendu (df -h /, systemctl is-active "
        "nginx, ls build/…).",
    )
    dossier: str = Field(default="~", min_length=1, max_length=1000, description="Son dossier.")


class PlanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    titre: str = Field(min_length=3, max_length=120, description="Titre court du plan.")
    etapes: list[StepIn] = Field(min_length=1, max_length=MAX_STEPS)
    mesure: MeasureIn | None = Field(
        default=None,
        description="Mode shell : une lecture prise avant puis après les étapes, la preuve "
        "que l'action a produit son effet.",
    )


def plan_tool_spec() -> ToolSpec:
    schema = PlanIn.model_json_schema()
    schema.pop("title", None)
    return ToolSpec(
        PLAN_TOOL,
        "Propose un plan d'étapes (outils et arguments) que l'utilisateur validera avant "
        "exécution. Obligatoire pour toute action de niveau 2 ou 3 et pour enchaîner "
        "plusieurs actions. Une étape peut reprendre le résultat d'une étape précédente "
        "avec {{etape N}} dans un argument texte. En mode shell, quand l'action doit changer "
        "un chiffre ou un état, ajoute une mesure : elle est prise avant et après.",
        schema,
    )


@dataclass(frozen=True)
class StepRecord:
    position: int
    tool: str
    arguments: dict[str, Any]
    why: str
    level: int
    description: str
    status: str
    result: str | None
    error: str | None


@dataclass(frozen=True)
class PlanRecord:
    id: str
    conversation_id: str | None
    title: str
    request: str
    status: str
    max_level: int
    tainted: bool
    created_at: datetime
    updated_at: datetime
    decided_at: datetime | None
    result: str | None
    steps: list[StepRecord]


def _readable(description: str) -> str:
    return PLACEHOLDER.sub(lambda m: f"le résultat de l'étape {m.group(1)}", description)


def _record(plan: Plan, steps: list[PlanStep]) -> PlanRecord:
    return PlanRecord(
        plan.id,
        plan.conversation_id,
        plan.title,
        plan.request,
        plan.status,
        plan.max_level,
        plan.tainted,
        plan.created_at,
        plan.updated_at,
        plan.decided_at,
        plan.result,
        [
            StepRecord(
                s.position,
                s.tool,
                dict(s.arguments),
                s.why,
                s.level,
                s.description,
                s.status,
                s.result,
                s.error,
            )
            for s in sorted(steps, key=lambda s: s.position)
        ],
    )


class PlanStore:
    def __init__(self, db: Database, gate: PermissionGate) -> None:
        self._db = db
        self._gate = gate

    async def create(
        self, plan: PlanIn, *, conversation_id: str | None, request: str, tainted: bool
    ) -> PlanRecord:
        """Vérifie chaque étape (outil, arguments, niveau) avant d'enregistrer le plan."""
        checked: list[tuple[StepIn, int, str]] = []
        for position, step in enumerate(plan.etapes, 1):
            for match in PLACEHOLDER.finditer(str(step.arguments)):
                if not 1 <= int(match.group(1)) < position:
                    raise InvalidInputError(
                        f"Étape {position} : {{{{etape {match.group(1)}}}}} ne désigne pas "
                        "une étape précédente."
                    )
            tool, args, level = self._gate.check(step.outil, step.arguments)
            if level >= Level.AGIR:
                for key, value in step.arguments.items():
                    if key not in tool.dynamic_fields and PLACEHOLDER.search(str(value)):
                        raise InvalidInputError(
                            f"Étape {position} : « {key} » doit être connu avant la validation "
                            "(on ne valide pas une action sur une cible inconnue)."
                        )
            checked.append((step, int(level), _readable(tool.describe(args))))
        now = utc_now()
        plan_id = uuid.uuid4().hex

        def write(session: Session) -> PlanRecord:
            row = Plan(
                id=plan_id,
                conversation_id=conversation_id,
                title=plan.titre,
                request=request[:4000],
                status="proposed",
                max_level=max(level for _, level, _ in checked),
                tainted=tainted,
                created_at=now,
                updated_at=now,
                decided_at=None,
                result=None,
            )
            session.add(row)
            steps = [
                PlanStep(
                    plan_id=plan_id,
                    position=position,
                    tool=step.outil,
                    arguments=step.arguments,
                    why=step.pourquoi,
                    level=level,
                    description=description[:500],
                    status="pending",
                    result=None,
                    error=None,
                    started_at=None,
                    ended_at=None,
                )
                for position, (step, level, description) in enumerate(checked, 1)
            ]
            session.add_all(steps)
            session.flush()
            return _record(row, steps)

        return await self._db.run(write)

    async def get(self, plan_id: str) -> PlanRecord:
        def read(session: Session) -> PlanRecord:
            row = session.get(Plan, plan_id)
            if row is None:
                raise NotFoundError("Plan introuvable.")
            steps = list(session.scalars(select(PlanStep).where(PlanStep.plan_id == plan_id)))
            return _record(row, steps)

        return await self._db.run(read)

    async def list(
        self,
        statuses: tuple[str, ...] = (),
        *,
        limit: int = 50,
        conversation_id: str | None = None,
    ) -> list[PlanRecord]:
        def read(session: Session) -> list[PlanRecord]:
            query = select(Plan).order_by(Plan.created_at.desc()).limit(limit)
            if statuses:
                query = query.where(Plan.status.in_(statuses))
            if conversation_id is not None:
                query = query.where(Plan.conversation_id == conversation_id)
            rows = list(session.scalars(query))
            ids = [r.id for r in rows]
            steps = list(session.scalars(select(PlanStep).where(PlanStep.plan_id.in_(ids))))
            by_plan: dict[str, list[PlanStep]] = {}
            for step in steps:
                by_plan.setdefault(step.plan_id, []).append(step)
            return [_record(r, by_plan.get(r.id, [])) for r in rows]

        return await self._db.run(read)

    async def set_status(self, plan_id: str, status: PlanStatus, *, decided: bool = False) -> None:
        now = utc_now()

        def write(session: Session) -> None:
            row = session.get(Plan, plan_id)
            if row is None:
                raise NotFoundError("Plan introuvable.")
            row.status = status
            row.updated_at = now
            if decided:
                row.decided_at = now

        await self._db.run(write)

    async def set_step(
        self,
        plan_id: str,
        position: int,
        *,
        status: StepStatus,
        result: str | None = None,
        error: str | None = None,
    ) -> None:
        now = utc_now()

        def write(session: Session) -> None:
            step = session.scalar(
                select(PlanStep).where(PlanStep.plan_id == plan_id, PlanStep.position == position)
            )
            if step is None:
                raise NotFoundError("Étape introuvable.")
            step.status = status
            if status == "running":
                step.started_at = now
            else:
                step.ended_at = now
            if result is not None:
                step.result = result[:8000]
            if error is not None:
                step.error = error[:500]

        await self._db.run(write)

    async def set_result(self, plan_id: str, status: PlanStatus, result: str) -> None:
        now = utc_now()

        def write(session: Session) -> None:
            row = session.get(Plan, plan_id)
            if row is None:
                raise NotFoundError("Plan introuvable.")
            row.status = status
            row.result = result
            row.updated_at = now

        await self._db.run(write)
