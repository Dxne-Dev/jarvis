"""Skills et plugins : voir chaque version (code, outils, tests), la tester, l'activer.

Activer un skill donne un nouvel outil à Jarvis : c'est « s'étendre » (niveau 3), donc une
double confirmation, écrite au journal. Le désactiver est immédiat ; supprimer une version
est une destruction (niveau 3).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict

from ojarvis.agent.executor import DoubleConfirmationRequiredError
from ojarvis.api.deps import ServicesDep
from ojarvis.services import Services
from ojarvis.skills.models import tool_name
from ojarvis.skills.service import SANDBOX_RULES
from ojarvis.skills.store import SkillRecord

router = APIRouter(prefix="/v1/skills")


class SkillToolOut(BaseModel):
    name: str
    tool: str
    description: str
    parameters: dict[str, Any]


class SkillOut(BaseModel):
    id: str
    name: str
    version: str
    description: str
    instructions: str
    status: str
    tools: list[SkillToolOut]
    permissions: str
    report: dict[str, Any] | None
    created_by: str
    conversation_id: str | None
    created_at: datetime
    tested_at: datetime | None
    activated_at: datetime | None
    digest: str


class SkillDetailOut(SkillOut):
    code: str
    tests: str


def _out(record: SkillRecord) -> dict[str, Any]:
    definition = record.definition
    return {
        "id": record.id,
        "name": record.name,
        "version": record.version,
        "description": definition.description,
        "instructions": definition.instructions,
        "status": record.status,
        "tools": [
            SkillToolOut(
                name=tool_name(record.name, t.nom),
                tool=t.nom,
                description=t.description,
                parameters=t.parametres,
            )
            for t in definition.outils
        ],
        "permissions": SANDBOX_RULES,
        "report": record.report.to_json() if record.report else None,
        "created_by": record.created_by,
        "conversation_id": record.conversation_id,
        "created_at": record.created_at,
        "tested_at": record.tested_at,
        "activated_at": record.activated_at,
        "digest": record.digest,
    }


class ConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    double_confirm: bool = False


async def _journal(
    services: Services, action: str, level: int, summary: str, **details: Any
) -> None:
    await services.journal.append(
        actor="utilisateur", action=action, level=level, summary=summary, details=details
    )


@router.get("")
async def list_skills(services: ServicesDep) -> list[SkillOut]:
    return [SkillOut.model_validate(_out(r)) for r in services.skills.records()]


@router.get("/{skill_id}")
async def get_skill(skill_id: str, services: ServicesDep) -> SkillDetailOut:
    record = await services.skills.get(skill_id)
    definition = record.definition
    return SkillDetailOut.model_validate(
        {**_out(record), "code": definition.code, "tests": definition.tests}
    )


@router.post("/{skill_id}/test")
async def test_skill(skill_id: str, services: ServicesDep) -> SkillOut:
    return SkillOut.model_validate(_out(await services.skills.retest(skill_id)))


@router.post("/{skill_id}/activate")
async def activate_skill(skill_id: str, body: ConfirmIn, services: ServicesDep) -> SkillOut:
    if not body.double_confirm:
        raise DoubleConfirmationRequiredError(
            "Activer un skill donne un nouvel outil à Jarvis : confirme une seconde fois."
        )
    record = await services.skills.activate(skill_id)
    await _journal(
        services,
        "skill.active",
        3,
        f"Skill activé : {record.label}",
        skill=record.id,
        empreinte=record.digest,
    )
    return SkillOut.model_validate(_out(record))


@router.post("/{skill_id}/disable")
async def disable_skill(skill_id: str, services: ServicesDep) -> SkillOut:
    record = await services.skills.disable(skill_id)
    await _journal(
        services, "skill.desactive", 2, f"Skill désactivé : {record.label}", skill=record.id
    )
    return SkillOut.model_validate(_out(record))


@router.delete("/{skill_id}", status_code=204)
async def delete_skill(
    skill_id: str, services: ServicesDep, double_confirm: bool = False
) -> Response:
    if not double_confirm:
        raise DoubleConfirmationRequiredError(
            "Supprimer une version d'un skill : confirme une seconde fois."
        )
    record = await services.skills.delete(skill_id)
    await _journal(
        services, "skill.supprime", 3, f"Skill supprimé : {record.label}", skill=record.id
    )
    return Response(status_code=204)
