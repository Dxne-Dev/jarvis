"""Tables du moteur. Toute modification passe par une migration Alembic."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ojarvis.db.base import Base


class Setting(Base):
    """Préférence non secrète (les secrets vont dans le trousseau)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[Any] = mapped_column(Text)  # JSON sérialisé
    updated_at: Mapped[datetime]


class SecretMeta(Base):
    """Ce qu'on sait d'un secret sans jamais stocker sa valeur."""

    __tablename__ = "secret_meta"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    source: Mapped[str] = mapped_column(String(16))  # env | ui | generated
    updated_at: Mapped[datetime]
    last_check_ok: Mapped[bool | None]
    last_check_at: Mapped[datetime | None]
    last_check_detail: Mapped[str | None] = mapped_column(String(300))
    last_check_latency_ms: Mapped[int | None]


class EventRecord(Base):
    __tablename__ = "events"
    __table_args__ = (Index("ix_events_type_id", "type", "id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime]
    type: Mapped[str] = mapped_column(String(96))
    source: Mapped[str] = mapped_column(String(64))
    correlation_id: Mapped[str | None] = mapped_column(String(32), index=True)
    payload: Mapped[dict[str, Any]]


class TraceRecord(Base):
    """Une requête suivie de bout en bout (tour de chat, tour vocal, test de clé...)."""

    __tablename__ = "traces"
    __table_args__ = (Index("ix_traces_started_at", "started_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    correlation_id: Mapped[str | None] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16))  # running | ok | error
    started_at: Mapped[datetime]
    ended_at: Mapped[datetime | None]
    duration_ms: Mapped[float | None]
    meta: Mapped[dict[str, Any]]
    error: Mapped[str | None] = mapped_column(String(500))


class SpanRecord(Base):
    """Une étape d'une trace : appel LLM, outil, transcription, synthèse vocale..."""

    __tablename__ = "spans"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    trace_id: Mapped[str] = mapped_column(ForeignKey("traces.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[str | None] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime]
    ended_at: Mapped[datetime | None]
    duration_ms: Mapped[float | None]
    attributes: Mapped[dict[str, Any]]
    error: Mapped[str | None] = mapped_column(String(500))
