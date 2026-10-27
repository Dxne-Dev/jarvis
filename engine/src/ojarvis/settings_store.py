"""Préférences non secrètes, validées par un modèle Pydantic et stockées en base."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ojarvis.core.clock import utc_now
from ojarvis.core.errors import InvalidInputError
from ojarvis.db.engine import Database
from ojarvis.db.models import Setting
from ojarvis.llm.types import TASK_TYPES
from ojarvis.voice.tts import DEFAULT_CARTESIA_VOICE

PROVIDERS = ("deepseek", "openrouter", "openai", "anthropic", "meta", "baseten", "ollama")
DEVICE_NAME = r"^[A-Za-z0-9._:@-]+$"


class Preferences(BaseModel):
    """Chaque phase ajoute ses champs ici, avec une valeur par défaut sûre."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    reduced_motion: Literal["system", "reduce", "full"] = "system"
    sphere_quality: Literal["auto", "high", "low"] = "auto"
    #: Modèle imposé par type de tâche, sous la forme « fournisseur/modèle » (absent = auto).
    routing: dict[str, str] = Field(default_factory=dict)
    #: Profil de modèles : « meta » met Muse Spark en tête de chaque tâche (les autres
    #: fournisseurs restent en secours). Désactivé par défaut.
    model_profile: Literal["auto", "meta"] = "auto"
    #: Profil « Tout Meta » : après ce nombre d'échecs de la même commande (un test toujours
    #: rouge), le tour suivant passe au modèle de relais, plus fort. 0 : relais coupé.
    relay_after: int = Field(default=2, ge=0, le=5)
    #: Le modèle de relais, « fournisseur/modèle » : Muse Wonder, le plus fort de Meta.
    relay_model: str = Field(default="meta/muse-wonder-1.0", max_length=120)
    #: Apprendre de la conversation (faits et préférences extraits automatiquement).
    learn_from_conversations: bool = True
    #: Voix : « Hey Jarvis », écoute, réponse parlée. Désactivable sans toucher au chat.
    voice_enabled: bool = True
    #: Noms PipeWire (« alsa_input.pci-… ») : ils sont passés à pactl, d'où un jeu de
    #: caractères strict (pas d'espace, donc pas d'option glissée en plus).
    voice_input_device: str | None = Field(default=None, max_length=200, pattern=DEVICE_NAME)
    voice_output_device: str | None = Field(default=None, max_length=200, pattern=DEVICE_NAME)
    #: Voix Cartesia (identifiant) ; Piper, local, sert de repli hors ligne.
    voice_name: str = Field(default=DEFAULT_CARTESIA_VOICE, pattern=r"^[0-9a-fA-F-]{8,64}$")
    voice_engine: Literal["auto", "piper"] = "auto"
    #: Transcription, après « Hey Jarvis » : Groq (Whisper large-v3, français imposé),
    #: Cartesia Ink-2 en flux, ou Whisper local seulement. Whisper local reste le secours.
    voice_stt: Literal["groq", "cartesia", "local"] = "groq"
    wake_sensitivity: Literal["basse", "normale", "haute"] = "normale"
    #: Après une réponse, écouter encore quelques secondes sans mot de réveil.
    voice_follow_up: bool = True
    #: Couper Jarvis en parlant (avec l'annulation d'écho ou un casque).
    voice_barge_in: bool = True
    voice_headset: bool = False
    #: Briefing du matin : à la première session du jour, Jarvis résume ta journée.
    briefing_enabled: bool = True
    #: Contrôle du PC (applications, écran, gestion des fichiers) : désactivé par défaut.
    os_control_enabled: bool = False
    #: Lecture de l'écran : modèle local (privé, lent ici) ou en ligne (rapide, l'image
    #: part chez le fournisseur). Une capture est une donnée sensible : local par défaut.
    screen_vision: Literal["local", "en_ligne"] = "local"

    @field_validator("voice_stt", mode="before")
    @classmethod
    def _legacy_stt(cls, value: object) -> object:
        return "groq" if value == "auto" else value  # ancienne valeur (avant Groq)

    @field_validator("routing")
    @classmethod
    def _check_routing(cls, value: dict[str, str]) -> dict[str, str]:
        for task, target in value.items():
            if task not in TASK_TYPES:
                raise ValueError(f"type de tâche inconnu : {task}")
            _check_target(target)
        return value

    @field_validator("relay_model")
    @classmethod
    def _check_relay_model(cls, value: str) -> str:
        _check_target(value)
        return value


def _check_target(target: str) -> None:
    """« fournisseur/modèle », d'un fournisseur connu."""
    provider, _, model = target.partition("/")
    if provider not in PROVIDERS or not model:
        raise ValueError(f"modèle invalide : {target}")


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

    async def get_state(self, key: str) -> Any:
        """État interne du moteur (ex. date du dernier briefing), hors préférences."""

        def read(session: Session) -> Any:
            row = session.get(Setting, f"etat.{key}")
            return json.loads(row.value) if row is not None else None

        return await self._db.run(read)

    async def set_state(self, key: str, value: Any) -> None:
        now = utc_now()

        def write(session: Session) -> None:
            session.merge(Setting(key=f"etat.{key}", value=json.dumps(value), updated_at=now))

        await self._db.run(write)

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
