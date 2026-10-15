"""Tables du moteur. Toute modification passe par une migration Alembic."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, LargeBinary, String, Text
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


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_updated_at", "updated_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    channel: Mapped[str] = mapped_column(String(16))  # app | voice | telegram
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
    archived: Mapped[bool] = mapped_column(default=False)


class ChatMessage(Base):
    """Un message d'une conversation. Clé entière : stable pour la recherche plein texte."""

    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation_created", "conversation_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="ok")  # ok | error | interrupted
    created_at: Mapped[datetime]
    provider: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(120))
    tokens_in: Mapped[int | None]
    tokens_out: Mapped[int | None]
    cost_usd: Mapped[float | None]
    latency_ms: Mapped[float | None]
    trace_id: Mapped[str | None] = mapped_column(String(32))
    meta: Mapped[dict[str, Any]]


class MemoryItem(Base):
    """Ce que Jarvis sait de toi : fait, préférence ou trait de profil. Visible et modifiable."""

    __tablename__ = "memory_items"
    __table_args__ = (Index("ix_memory_items_kind", "kind"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(16))  # fait | preference | profil
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16))  # conversation | manuel
    source_message_id: Mapped[int | None]
    confidence: Mapped[float]
    pinned: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
    last_used_at: Mapped[datetime | None]
    use_count: Mapped[int] = mapped_column(default=0)


class Embedding(Base):
    """Vecteur d'un souvenir ou d'un message. Source de vérité ; l'index vec0 en dérive."""

    __tablename__ = "embeddings"

    owner_type: Mapped[str] = mapped_column(String(16), primary_key=True)  # memory | message
    owner_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model: Mapped[str] = mapped_column(String(64), primary_key=True)
    dim: Mapped[int]
    vector: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime]


class AuditEntry(Base):
    """Journal des actions : ajout seul, chaîné par SHA-256 (des déclencheurs refusent toute
    modification ou suppression). Vérifié à chaque démarrage."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime]
    actor: Mapped[str] = mapped_column(String(32))  # utilisateur | jarvis | automatisation
    action: Mapped[str] = mapped_column(String(64))
    level: Mapped[int]
    summary: Mapped[str] = mapped_column(String(500))
    details: Mapped[dict[str, Any]]
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)


class Plan(Base):
    """Un plan proposé par Jarvis : rien de niveau 2 ou 3 ne s'exécute avant sa validation."""

    __tablename__ = "plans"
    __table_args__ = (Index("ix_plans_status", "status"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(200))
    request: Mapped[str] = mapped_column(Text)  # la demande de l'utilisateur, pour la synthèse
    status: Mapped[str] = mapped_column(String(16))
    max_level: Mapped[int]
    #: Proposé après lecture d'un contenu externe (page, fichier) : vigilance à la validation.
    tainted: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
    decided_at: Mapped[datetime | None]
    result: Mapped[str | None] = mapped_column(Text)


class PlanStep(Base):
    __tablename__ = "plan_steps"
    __table_args__ = (Index("ix_plan_steps_plan_position", "plan_id", "position"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"))
    position: Mapped[int]
    tool: Mapped[str] = mapped_column(String(64))
    arguments: Mapped[dict[str, Any]]
    why: Mapped[str] = mapped_column(String(500))
    level: Mapped[int]
    description: Mapped[str] = mapped_column(String(500))  # ce qui va se passer, sur quoi
    status: Mapped[str] = mapped_column(String(16))
    result: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(String(500))
    started_at: Mapped[datetime | None]
    ended_at: Mapped[datetime | None]


class CookieGrant(Base):
    """Cookies d'un domaine importés dans le navigateur de Jarvis, avec ton accord."""

    __tablename__ = "browser_cookie_grants"

    domain: Mapped[str] = mapped_column(String(253), primary_key=True)
    source: Mapped[str] = mapped_column(String(32))  # brave | chrome | chromium
    imported_at: Mapped[datetime]
    count: Mapped[int]
    revoked_at: Mapped[datetime | None]
