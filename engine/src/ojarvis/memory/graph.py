"""Mémoire graphe : les personnes, projets, événements et lieux de ta vie, et ce qui les relie.

Remplie par l'extraction des conversations (le même appel que les faits) ou par toi ; visible
et modifiable dans l'écran Mémoire. Une entité par nom (comparé sans majuscules ni accents) ;
« moi », c'est toi.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ojarvis.core.clock import utc_now
from ojarvis.core.errors import ConflictError, InvalidInputError, NotFoundError
from ojarvis.db.engine import Database
from ojarvis.db.models import GraphEntity, GraphRelation
from ojarvis.events.bus import EventBus
from ojarvis.security.redaction import REDACTOR

EntityKind = Literal["moi", "personne", "projet", "evenement", "lieu", "organisation", "sujet"]
ENTITY_KINDS: tuple[EntityKind, ...] = (
    "moi",
    "personne",
    "projet",
    "evenement",
    "lieu",
    "organisation",
    "sujet",
)
ME = "moi"


def name_key(name: str) -> str:
    folded = unicodedata.normalize("NFKD", name.casefold())
    return " ".join("".join(c for c in folded if not unicodedata.combining(c)).split())[:120]


def _clean(text: str, limit: int, what: str) -> str:
    cleaned = " ".join(REDACTOR.redact(text).split())[:limit]
    if not cleaned:
        raise InvalidInputError(f"{what} vide.")
    return cleaned


@dataclass(frozen=True)
class EntityRecord:
    id: int
    kind: str
    name: str
    description: str | None
    source: str
    mentions: int
    created_at: datetime
    last_seen_at: datetime


@dataclass(frozen=True)
class RelationRecord:
    id: int
    source_id: int
    target_id: int
    label: str
    mentions: int
    last_seen_at: datetime


def _entity(row: GraphEntity) -> EntityRecord:
    return EntityRecord(
        id=row.id,
        kind=row.kind,
        name=row.name,
        description=row.description,
        source=row.source,
        mentions=row.mentions,
        created_at=row.created_at,
        last_seen_at=row.last_seen_at,
    )


def _relation(row: GraphRelation) -> RelationRecord:
    return RelationRecord(
        id=row.id,
        source_id=row.source_id,
        target_id=row.target_id,
        label=row.label,
        mentions=row.mentions,
        last_seen_at=row.last_seen_at,
    )


class GraphStore:
    def __init__(
        self, db: Database, bus: EventBus, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._db = db
        self._bus = bus
        self._clock = clock

    # ------------------------------------------------------------------ écriture

    @staticmethod
    def _upsert(
        session: Session,
        name: str,
        kind: str,
        description: str | None,
        *,
        source: str,
        now: datetime,
    ) -> GraphEntity:
        """L'entité de ce nom (vue une fois de plus), ou une nouvelle."""
        if kind == ME:
            name = "Moi"
        key = ME if kind == ME else name_key(name)
        row = session.scalars(select(GraphEntity).where(GraphEntity.name_key == key)).first()
        if row is None:
            row = GraphEntity(
                kind=kind,
                name=name,
                name_key=key,
                description=description,
                source=source,
                mentions=1,
                created_at=now,
                updated_at=now,
                last_seen_at=now,
            )
            session.add(row)
            session.flush()
            return row
        row.mentions += 1
        row.last_seen_at = now
        if description and not row.description:
            row.description = description
            row.updated_at = now
        return row

    async def remember(
        self,
        entities: list[tuple[str, str, str | None]],
        relations: list[tuple[str, str, str]],
        *,
        source: str = "conversation",
    ) -> tuple[int, int]:
        """Ajoute ce qu'une conversation a appris : (nom, type, description) et
        (source, lien, cible). Rend (entités vues, relations vues)."""
        now = self._clock()

        def write(session: Session) -> tuple[int, int]:
            by_name: dict[str, GraphEntity] = {}
            for name, kind, description in entities:
                if kind not in ENTITY_KINDS:
                    continue
                clean = _clean(name, 120, "Nom")
                about = (
                    " ".join(REDACTOR.redact(description).split())[:300] if description else None
                )
                row = self._upsert(session, clean, kind, about, source=source, now=now)
                by_name[ME if kind == ME else name_key(clean)] = row
            linked = 0
            for left, label, right in relations:
                a = by_name.get(ME if left.strip().casefold() == ME else name_key(left))
                b = by_name.get(ME if right.strip().casefold() == ME else name_key(right))
                if a is None or b is None or a.id == b.id:
                    continue
                self._link(session, a.id, _clean(label, 80, "Lien"), b.id, now)
                linked += 1
            return len(by_name), linked

        counts = await self._db.run(write)
        if any(counts):
            await self._bus.publish(
                "memory.graph", {"entities": counts[0], "relations": counts[1]}, source="memory"
            )
        return counts

    @staticmethod
    def _link(
        session: Session, source_id: int, label: str, target_id: int, now: datetime
    ) -> GraphRelation:
        row = session.scalars(
            select(GraphRelation).where(
                GraphRelation.source_id == source_id,
                GraphRelation.target_id == target_id,
                GraphRelation.label == label,
            )
        ).first()
        if row is None:
            row = GraphRelation(
                source_id=source_id,
                target_id=target_id,
                label=label,
                mentions=1,
                created_at=now,
                last_seen_at=now,
            )
            session.add(row)
            session.flush()
        else:
            row.mentions += 1
            row.last_seen_at = now
        return row

    async def add_entity(self, name: str, kind: str, description: str | None) -> EntityRecord:
        if kind not in ENTITY_KINDS:
            raise InvalidInputError(f"Type inconnu : {kind}.")
        now = self._clock()
        clean = _clean(name, 120, "Nom")

        def write(session: Session) -> EntityRecord:
            key = ME if kind == ME else name_key(clean)
            if session.scalars(select(GraphEntity).where(GraphEntity.name_key == key)).first():
                raise ConflictError(f"« {clean} » est déjà dans la mémoire.")
            row = self._upsert(session, clean, kind, description, source="utilisateur", now=now)
            return _entity(row)

        record = await self._db.run(write)
        await self._bus.publish("memory.graph", {"entity": record.id}, source="memory")
        return record

    async def update_entity(
        self,
        entity_id: int,
        *,
        name: str | None = None,
        kind: str | None = None,
        description: str | None = None,
    ) -> EntityRecord:
        now = self._clock()

        def write(session: Session) -> EntityRecord:
            row = session.get(GraphEntity, entity_id)
            if row is None:
                raise NotFoundError("Entité introuvable.")
            if name is not None and row.kind != ME:
                clean = _clean(name, 120, "Nom")
                key = name_key(clean)
                other = session.scalars(
                    select(GraphEntity).where(GraphEntity.name_key == key)
                ).first()
                if other is not None and other.id != row.id:
                    raise ConflictError(f"« {clean} » existe déjà.")
                row.name, row.name_key = clean, key
            if kind is not None and row.kind != ME:
                if kind not in ENTITY_KINDS or kind == ME:
                    raise InvalidInputError(f"Type inconnu : {kind}.")
                row.kind = kind
            if description is not None:
                row.description = " ".join(description.split())[:300] or None
            row.updated_at = now
            return _entity(row)

        record = await self._db.run(write)
        await self._bus.publish("memory.graph", {"entity": record.id}, source="memory")
        return record

    async def delete_entity(self, entity_id: int) -> None:
        def write(session: Session) -> None:
            row = session.get(GraphEntity, entity_id)
            if row is None:
                raise NotFoundError("Entité introuvable.")
            session.delete(row)  # ses relations partent avec elle (cascade)

        await self._db.run(write)
        await self._bus.publish("memory.graph", {"deleted": entity_id}, source="memory")

    async def add_relation(self, source_id: int, label: str, target_id: int) -> RelationRecord:
        if source_id == target_id:
            raise InvalidInputError("Une entité ne se relie pas à elle-même.")
        now = self._clock()
        clean = _clean(label, 80, "Lien")

        def write(session: Session) -> RelationRecord:
            for entity_id in (source_id, target_id):
                if session.get(GraphEntity, entity_id) is None:
                    raise NotFoundError("Entité introuvable.")
            return _relation(self._link(session, source_id, clean, target_id, now))

        record = await self._db.run(write)
        await self._bus.publish("memory.graph", {"relation": record.id}, source="memory")
        return record

    async def delete_relation(self, relation_id: int) -> None:
        def write(session: Session) -> None:
            row = session.get(GraphRelation, relation_id)
            if row is None:
                raise NotFoundError("Lien introuvable.")
            session.delete(row)

        await self._db.run(write)
        await self._bus.publish("memory.graph", {"deleted_relation": relation_id}, source="memory")

    # ------------------------------------------------------------------ lecture

    async def graph(self, *, limit: int = 300) -> tuple[list[EntityRecord], list[RelationRecord]]:
        """Les entités les plus citées, et les liens entre elles."""

        def read(session: Session) -> tuple[list[EntityRecord], list[RelationRecord]]:
            rows = list(
                session.scalars(
                    select(GraphEntity)
                    .order_by(GraphEntity.mentions.desc(), GraphEntity.last_seen_at.desc())
                    .limit(limit)
                )
            )
            ids = [r.id for r in rows]
            links = session.scalars(
                select(GraphRelation).where(
                    GraphRelation.source_id.in_(ids), GraphRelation.target_id.in_(ids)
                )
            )
            return [_entity(r) for r in rows], [_relation(r) for r in links]

        return await self._db.run(read)

    async def known_names(self, limit: int = 40) -> list[tuple[str, str]]:
        """(nom, type) des entités connues : aide l'extraction à réutiliser les mêmes noms."""
        entities, _ = await self.graph(limit=limit)
        return [(e.name, e.kind) for e in entities]

    async def about(self, text: str, *, limit: int = 6) -> list[str]:
        """Ce que le graphe sait des entités citées dans un texte (pour le contexte)."""
        folded = name_key(text)

        def read(session: Session) -> list[str]:
            rows = [
                r
                for r in session.scalars(select(GraphEntity).where(GraphEntity.kind != ME))
                if len(r.name_key) >= 3 and r.name_key in folded
            ][:limit]
            lines = []
            names = {r.id: r.name for r in session.scalars(select(GraphEntity))}
            for row in rows:
                links = session.scalars(
                    select(GraphRelation).where(
                        or_(GraphRelation.source_id == row.id, GraphRelation.target_id == row.id)
                    )
                )
                facts = [
                    " ".join(
                        (names.get(link.source_id, "?"), link.label, names.get(link.target_id, "?"))
                    )
                    for link in links
                ][:5]
                about = f" — {row.description}" if row.description else ""
                lines.append(
                    f"{row.name} ({row.kind}){about}" + (f" : {'; '.join(facts)}" if facts else "")
                )
            return lines

        return await self._db.run(read)
