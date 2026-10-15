"""Suggestions de Jarvis : celles qui attendent, les accepter (une option) ou les écarter."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from ojarvis.anticipation.store import Suggestion
from ojarvis.api.deps import ServicesDep

router = APIRouter(prefix="/v1/suggestions")


class OptionOut(BaseModel):
    id: str
    label: str


class SuggestionOut(BaseModel):
    id: str
    kind: str
    title: str
    detail: str | None
    options: list[OptionOut]
    confidence: float
    status: str
    conversation_id: str | None
    created_at: datetime


class AcceptIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option: str = Field(min_length=1, max_length=40)


def _out(suggestion: Suggestion) -> SuggestionOut:
    return SuggestionOut(
        id=suggestion.id,
        kind=suggestion.kind,
        title=suggestion.title,
        detail=suggestion.detail,
        options=[OptionOut(id=o.id, label=o.label) for o in suggestion.options],
        confidence=suggestion.confidence,
        status=suggestion.status,
        conversation_id=suggestion.conversation_id,
        created_at=suggestion.created_at,
    )


@router.get("")
async def pending_suggestions(services: ServicesDep) -> list[SuggestionOut]:
    return [_out(s) for s in await services.anticipation.store.pending()]


@router.post("/anticipate")
async def anticipate(services: ServicesDep) -> list[SuggestionOut]:
    """Repasse tout de suite sur tes habitudes (sinon, toutes les 6 heures)."""
    return [_out(s) for s in await services.anticipation.anticipate()]


@router.post("/{suggestion_id}/accept")
async def accept_suggestion(
    suggestion_id: str, body: AcceptIn, services: ServicesDep
) -> SuggestionOut:
    return _out(await services.anticipation.accept(suggestion_id, body.option))


@router.post("/{suggestion_id}/dismiss")
async def dismiss_suggestion(suggestion_id: str, services: ServicesDep) -> SuggestionOut:
    return _out(await services.anticipation.dismiss(suggestion_id))
