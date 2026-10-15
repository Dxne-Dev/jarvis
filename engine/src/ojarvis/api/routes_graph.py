"""Mémoire graphe : voir, corriger, compléter ou effacer les entités et leurs liens."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from ojarvis.api.deps import ServicesDep
from ojarvis.memory.graph import EntityKind, EntityRecord, RelationRecord

router = APIRouter(prefix="/v1/memory/graph")


class EntityOut(BaseModel):
    id: int
    kind: str
    name: str
    description: str | None
    source: str
    mentions: int
    created_at: datetime
    last_seen_at: datetime


class RelationOut(BaseModel):
    id: int
    source_id: int
    target_id: int
    label: str
    mentions: int
    last_seen_at: datetime


class GraphOut(BaseModel):
    entities: list[EntityOut]
    relations: list[RelationOut]


class EntityIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    kind: EntityKind
    description: str | None = Field(default=None, max_length=300)


class EntityPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    kind: EntityKind | None = None
    description: str | None = Field(default=None, max_length=300)


class RelationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: int
    label: str = Field(min_length=2, max_length=80)
    target_id: int


def _entity(record: EntityRecord) -> EntityOut:
    return EntityOut.model_validate(record, from_attributes=True)


def _relation(record: RelationRecord) -> RelationOut:
    return RelationOut.model_validate(record, from_attributes=True)


@router.get("")
async def get_graph(
    services: ServicesDep, limit: Annotated[int, Query(ge=1, le=500)] = 300
) -> GraphOut:
    entities, relations = await services.graph.graph(limit=limit)
    return GraphOut(
        entities=[_entity(e) for e in entities], relations=[_relation(r) for r in relations]
    )


@router.post("/entities", status_code=201)
async def add_entity(body: EntityIn, services: ServicesDep) -> EntityOut:
    return _entity(await services.graph.add_entity(body.name, body.kind, body.description))


@router.patch("/entities/{entity_id}")
async def update_entity(entity_id: int, body: EntityPatch, services: ServicesDep) -> EntityOut:
    return _entity(
        await services.graph.update_entity(
            entity_id, name=body.name, kind=body.kind, description=body.description
        )
    )


@router.delete("/entities/{entity_id}", status_code=204)
async def delete_entity(entity_id: int, services: ServicesDep) -> Response:
    await services.graph.delete_entity(entity_id)
    return Response(status_code=204)


@router.post("/relations", status_code=201)
async def add_relation(body: RelationIn, services: ServicesDep) -> RelationOut:
    return _relation(await services.graph.add_relation(body.source_id, body.label, body.target_id))


@router.delete("/relations/{relation_id}", status_code=204)
async def delete_relation(relation_id: int, services: ServicesDep) -> Response:
    await services.graph.delete_relation(relation_id)
    return Response(status_code=204)
