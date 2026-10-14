"""Identifiant de corrélation propagé dans les logs, les événements et les traces."""

from __future__ import annotations

import uuid
from contextvars import ContextVar

correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def new_correlation_id() -> str:
    return uuid.uuid4().hex[:16]


def current_correlation_id() -> str | None:
    return correlation_id_var.get()
