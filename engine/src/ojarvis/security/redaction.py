"""Masquage des secrets dans tout texte qui sort du moteur (logs, événements, traces)."""

from __future__ import annotations

import re
import threading
from collections.abc import Iterable, Mapping
from typing import Any

MASK = "***"

# Formats de clés connus, masqués même s'ils ne viennent pas du trousseau.
_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bsk_car_[A-Za-z0-9]{10,}"),
    re.compile(r"\bghp_[A-Za-z0-9]{30,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}"),
    re.compile(r"\bntn_[A-Za-z0-9]{30,}"),
    re.compile(r"\bsecret_[A-Za-z0-9]{30,}"),
    re.compile(r"\btvly-[A-Za-z0-9-]{16,}"),
    re.compile(r"\bGOCSPX-[A-Za-z0-9_-]{16,}"),
    re.compile(r"(?<![0-9])\d{8,12}:AA[A-Za-z0-9_-]{30,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)

_MIN_SECRET_LENGTH = 6


class Redactor:
    """Remplace les valeurs secrètes connues et les formats de clés par `***`."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: tuple[str, ...] = ()

    def set_values(self, values: Iterable[str]) -> None:
        cleaned = {v for v in values if v and len(v) >= _MIN_SECRET_LENGTH}
        # Les plus longues d'abord : une valeur peut en contenir une autre.
        with self._lock:
            self._values = tuple(sorted(cleaned, key=len, reverse=True))

    def add_value(self, value: str) -> None:
        with self._lock:
            current = set(self._values)
        current.add(value)
        self.set_values(current)

    def redact(self, text: str) -> str:
        for value in self._values:
            if value in text:
                text = text.replace(value, MASK)
        for pattern in _PATTERNS:
            text = pattern.sub(MASK, text)
        return text

    def redact_obj(self, obj: Any) -> Any:
        """Masque récursivement les chaînes d'une structure JSON."""
        if isinstance(obj, str):
            return self.redact(obj)
        if isinstance(obj, Mapping):
            return {key: self.redact_obj(val) for key, val in obj.items()}
        if isinstance(obj, list | tuple):
            return [self.redact_obj(item) for item in obj]
        return obj


REDACTOR = Redactor()
