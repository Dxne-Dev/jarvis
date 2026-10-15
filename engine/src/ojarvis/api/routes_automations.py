"""Automatisations : CRUD complet depuis l'interface, lancement à la demande, historique.

Créer ou modifier une automatisation est une action (niveau 2), la supprimer une
destruction (niveau 3) : faites depuis l'interface, elles sont écrites au journal.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from ojarvis.api.deps import ServicesDep
from ojarvis.automations.models import EVENTS, Action, Trigger
from ojarvis.automations.store import AutomationRecord
from ojarvis.services import Services
from ojarvis.workflows.engine import RunRecord

router = APIRouter(prefix="/v1/automations")


class AutomationOut(BaseModel):
    id: str
    name: str
    trigger: dict[str, Any]
    action: dict[str, Any]
    when: str
    what: str
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


def _out(record: AutomationRecord) -> AutomationOut:
    return AutomationOut(
        id=record.id,
        name=record.name,
        trigger=record.trigger.model_dump(),
        action=record.action.model_dump(),
        when=record.when,
        what=record.what,
        enabled=record.enabled,
        one_shot=record.one_shot,
        created_by=record.created_by,
        created_at=record.created_at,
        updated_at=record.updated_at,
        next_run_at=record.next_run_at,
        last_run_at=record.last_run_at,
        last_status=record.last_status,
        run_count=record.run_count,
        conversation_id=record.conversation_id,
    )


class RunOut(BaseModel):
    id: str
    title: str
    status: str
    position: int
    steps: int
    attempts: int
    error: str | None
    reason: str | None
    summary: str | None
    plans: list[str]
    conversation_id: str | None
    created_at: datetime
    ended_at: datetime | None


def _run(record: RunRecord) -> RunOut:
    context = record.context
    return RunOut(
        id=record.id,
        title=record.title,
        status=record.status,
        position=record.position,
        steps=len(record.steps),
        attempts=record.attempts,
        error=record.error,
        reason=context.get("raison"),
        summary=(context.get("reponse") or None),
        plans=[str(p) for p in context.get("plans", [])],
        conversation_id=context.get("conversation_id"),
        created_at=record.created_at,
        ended_at=record.ended_at,
    )


class AutomationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=120)
    trigger: Trigger
    action: Action


class AutomationPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=2, max_length=120)
    trigger: Trigger | None = None
    action: Action | None = None
    enabled: bool | None = None


async def _journal(
    services: Services, action: str, level: int, summary: str, **details: Any
) -> None:
    await services.journal.append(
        actor="utilisateur", action=action, level=level, summary=summary, details=details
    )


@router.get("")
async def list_automations(services: ServicesDep) -> list[AutomationOut]:
    return [_out(r) for r in await services.automations.all()]


@router.get("/events")
async def trigger_events() -> list[dict[str, str]]:
    """Événements qui peuvent déclencher une automatisation (pour le formulaire)."""
    return [{"type": key, "label": label} for key, label in EVENTS.items()]


@router.post("", status_code=201)
async def create_automation(body: AutomationIn, services: ServicesDep) -> AutomationOut:
    record = await services.automations.create(
        body.name, body.trigger, body.action, created_by="utilisateur"
    )
    await services.scheduler.reload()
    await _journal(
        services,
        "automatisation.creee",
        2,
        f"Automatisation créée : {record.summary()}",
        id=record.id,
    )
    return _out(record)


@router.get("/{automation_id}")
async def get_automation(automation_id: str, services: ServicesDep) -> AutomationOut:
    return _out(await services.automations.get(automation_id))


@router.patch("/{automation_id}")
async def update_automation(
    automation_id: str, body: AutomationPatch, services: ServicesDep
) -> AutomationOut:
    record = await services.automations.update(
        automation_id,
        name=body.name,
        trigger=body.trigger,
        action=body.action,
        enabled=body.enabled,
    )
    await services.scheduler.reload()
    await _journal(
        services,
        "automatisation.modifiee",
        2,
        f"Automatisation modifiée : {record.summary()}"
        + ("" if record.enabled else " (désactivée)"),
        id=record.id,
        changements=sorted(body.model_dump(exclude_none=True)),
    )
    return _out(record)


@router.delete("/{automation_id}", status_code=204)
async def delete_automation(automation_id: str, services: ServicesDep) -> Response:
    record = await services.automations.delete(automation_id)
    await services.scheduler.reload()
    await _journal(
        services,
        "automatisation.supprimee",
        3,
        f"Automatisation supprimée : {record.summary()}",
        id=record.id,
    )
    return Response(status_code=204)


@router.post("/{automation_id}/run")
async def run_automation(automation_id: str, services: ServicesDep) -> RunOut:
    """Lancer tout de suite (comme à l'heure dite)."""
    record = await services.automations.get(automation_id)
    run = await services.scheduler.fire(record, reason="manuel")
    return _run(run)


@router.get("/{automation_id}/runs")
async def automation_runs(
    automation_id: str,
    services: ServicesDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[RunOut]:
    await services.automations.get(automation_id)
    return [
        _run(r) for r in await services.workflows.runs(automation_id=automation_id, limit=limit)
    ]
