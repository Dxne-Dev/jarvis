"""Préférences non secrètes, validées par un modèle Pydantic et stockées en base."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ojarvis.core.clock import utc_now
from ojarvis.core.errors import InvalidInputError
from ojarvis.db.engine import Database
from ojarvis.db.models import Setting


class Preferences(BaseModel):
    """Chaque phase ajoute ses champs ici, avec une valeur par défaut sûre."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    reduced_motion: Literal["system", "reduce", "full"] = "system"
    sphere_quality: Literal["auto", "high", "low"] = "auto"


class SettingsStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    def _read(self, session: Session) -> Preferences:
        stored = {row.key: json.loads(row.value) for row in session.scalars(select(Setting))}
        known = {k: v for k, v in stored.items() if k in Preferences.model_fields}
        try:
            return Preferences(**known)
        except ValidationError:
            # Une valeur devenue invalide (champ renommé, ancien format) reprend son défaut.
            safe: dict[str, Any] = {}
            for key, value in known.items():
                try:
                    Preferences(**{key: value})
                except ValidationError:
                    continue
                safe[key] = value
            return Preferences(**safe)

    async def get(self) -> Preferences:
        return await self._db.run(self._read)

    async def update(self, changes: dict[str, Any]) -> tuple[Preferences, list[str]]:
        unknown = sorted(set(changes) - set(Preferences.model_fields))
        if unknown:
            raise InvalidInputError(f"Réglage inconnu : {', '.join(unknown)}.")

        def write(session: Session) -> tuple[Preferences, list[str]]:
            current = self._read(session)
            try:
                updated = current.model_copy(update=changes)
                Preferences.model_validate(updated.model_dump())
            except ValidationError as exc:
                raise InvalidInputError("Valeur de réglage invalide.") from exc
            changed = [k for k in changes if getattr(current, k) != getattr(updated, k)]
            now = utc_now()
            for key in changed:
                session.merge(
                    Setting(key=key, value=json.dumps(getattr(updated, key)), updated_at=now)
                )
            return updated, changed

        return await self._db.run(write)
