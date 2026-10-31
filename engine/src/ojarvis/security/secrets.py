"""Secrets : valeurs dans le trousseau du système, métadonnées (jamais la valeur) en base.

Une valeur enregistrée n'est jamais renvoyée à l'interface. Seuls les noms du catalogue
sont acceptés, et seuls ces noms sont importés depuis le `.env` de développement.
"""

from __future__ import annotations

import contextlib
import re
import secrets as pysecrets
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from ojarvis.core.clock import utc_now
from ojarvis.core.errors import InvalidInputError, NotFoundError, UnavailableError
from ojarvis.core.logs import get_logger
from ojarvis.db.engine import Database
from ojarvis.db.models import SecretMeta
from ojarvis.security.redaction import REDACTOR, Redactor

log = get_logger(__name__)

KEYRING_SERVICE = "o-jarvis"
LOCAL_KEY_NAME = "OJARVIS_LOCAL_KEY"

Group = Literal["llm", "voice", "search", "integrations", "phone"]
Source = Literal["env", "ui", "generated"]


@dataclass(frozen=True, slots=True)
class SecretSpec:
    name: str
    label: str
    group: Group
    help: str


CATALOG: tuple[SecretSpec, ...] = (
    SecretSpec("DEEPSEEK_API_KEY", "DeepSeek", "llm", "LLM principal."),
    SecretSpec("OPENROUTER_API_KEY", "OpenRouter", "llm", "LLM secondaire et vision."),
    SecretSpec("OPENAI_API_KEY", "OpenAI", "llm", "Optionnel."),
    SecretSpec("ANTHROPIC_API_KEY", "Anthropic", "llm", "Optionnel."),
    SecretSpec("MODEL_API_KEY", "Meta", "llm", "Muse Spark, Muse Wonder (dev.meta.ai)."),
    SecretSpec("BASETEN_API_KEY", "Baseten", "llm", "Muse Spark Open, en secours de Muse Spark."),
    SecretSpec("CARTESIA_API_KEY", "Cartesia", "voice", "Synthèse vocale Sonic."),
    SecretSpec("GROQ_API_KEY", "Groq", "voice", "Transcription Whisper large-v3."),
    SecretSpec("TAVILY_API_KEY", "Tavily", "search", "Recherche web."),
    SecretSpec("GITHUB_TOKEN", "GitHub", "integrations", "Jeton fine-grained."),
    SecretSpec("NOTION_TOKEN", "Notion", "integrations", "Intégration interne."),
    SecretSpec("GOOGLE_CLIENT_ID", "Google — client", "integrations", "OAuth « Desktop app »."),
    SecretSpec(
        "GOOGLE_CLIENT_SECRET", "Google — secret", "integrations", "Secret du client OAuth."
    ),
    SecretSpec("TELEGRAM_BOT_TOKEN", "Telegram — bot", "phone", "Jeton du bot (@BotFather)."),
    SecretSpec("TELEGRAM_ALLOWED_USER_ID", "Telegram — ton ID", "phone", "Seul expéditeur servi."),
)
CATALOG_BY_NAME: Mapping[str, SecretSpec] = {spec.name: spec for spec in CATALOG}


class SecretBackend(Protocol):
    name: str

    def get(self, key: str) -> str | None: ...

    def set(self, key: str, value: str) -> None: ...

    def delete(self, key: str) -> None: ...


class MemoryBackend:
    """Trousseau en mémoire, pour les tests."""

    name = "memoire"

    def __init__(self) -> None:
        self._values: dict[str, str] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> str | None:
        with self._lock:
            return self._values.get(key)

    def set(self, key: str, value: str) -> None:
        with self._lock:
            self._values[key] = value

    def delete(self, key: str) -> None:
        with self._lock:
            self._values.pop(key, None)


class KeyringBackend:
    """Trousseau du système (Secret Service). Refuse tout repli en clair sur disque."""

    def __init__(self) -> None:
        import keyring  # noqa: PLC0415
        from keyring.backends import fail  # noqa: PLC0415

        backend = keyring.get_keyring()
        chain = list(getattr(backend, "backends", [backend]))
        # Refus : aucun trousseau, trousseau nul (n'enregistre rien) ou fichier en clair.
        usable = [
            b
            for b in chain
            if not isinstance(b, fail.Keyring)
            and type(b).__module__ != "keyring.backends.null"
            and type(b).__name__ != "PlaintextKeyring"
        ]
        if not usable:
            raise UnavailableError(
                "Trousseau du système indisponible (Secret Service).", code="keyring_unavailable"
            )
        self._keyring = keyring
        module = type(backend).__module__
        self.name = "Secret Service" if module.endswith("SecretService") else type(backend).__name__

    def get(self, key: str) -> str | None:
        value: str | None = self._keyring.get_password(KEYRING_SERVICE, key)
        return value

    def set(self, key: str, value: str) -> None:
        self._keyring.set_password(KEYRING_SERVICE, key, value)

    def delete(self, key: str) -> None:
        import keyring.errors  # noqa: PLC0415

        with contextlib.suppress(keyring.errors.PasswordDeleteError):
            self._keyring.delete_password(KEYRING_SERVICE, key)


@dataclass(frozen=True, slots=True)
class SecretStatus:
    name: str
    label: str
    group: Group
    help: str
    configured: bool
    source: str | None
    updated_at: datetime | None
    last_check_ok: bool | None
    last_check_at: datetime | None
    last_check_detail: str | None
    last_check_latency_ms: int | None


_ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


def parse_dotenv(path: Path, allowed: Iterable[str]) -> dict[str, str]:
    """Lit un `.env` en ne gardant que les noms autorisés et les valeurs non vides."""
    allowed_set = set(allowed)
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = _ENV_LINE.match(line)
        if not match or match.group(1) not in allowed_set:
            continue
        raw = match.group(2).strip()
        if raw.startswith(("'", '"')) and len(raw) >= 2 and raw[-1] == raw[0]:
            value = raw[1:-1]
        elif raw.startswith("#"):
            value = ""
        else:
            value = re.sub(r"\s+#.*$", "", raw).strip()
        if value:
            values[match.group(1)] = value
    return values


class SecretStore:
    def __init__(self, db: Database, backend: SecretBackend, redactor: Redactor = REDACTOR) -> None:
        self._db = db
        self._backend = backend
        self._redactor = redactor
        # Les valeurs sont déjà en mémoire (filtre des logs) : ce cache évite un appel D-Bus
        # au trousseau à chaque requête vers un modèle.
        self._cache: dict[str, str | None] = {}
        self._cache_lock = threading.Lock()

    @property
    def backend_name(self) -> str:
        return self._backend.name

    @staticmethod
    def spec(name: str) -> SecretSpec:
        spec = CATALOG_BY_NAME.get(name)
        if spec is None:
            raise NotFoundError(f"Secret inconnu : {name}.")
        return spec

    def get(self, name: str) -> str | None:
        """Usage interne au moteur uniquement : jamais exposé par l'API."""
        if name != LOCAL_KEY_NAME:
            self.spec(name)
        with self._cache_lock:
            if name in self._cache:
                return self._cache[name]
        value = self._backend.get(name)
        with self._cache_lock:
            self._cache[name] = value
        return value

    def _forget(self, name: str) -> None:
        with self._cache_lock:
            self._cache.pop(name, None)

    def set(self, name: str, value: str, *, source: Source = "ui") -> None:
        self.spec(name)
        cleaned = value.strip()
        if not cleaned or len(cleaned) > 4096 or any(c in cleaned for c in "\r\n\0"):
            raise InvalidInputError("Valeur de secret invalide.")
        self._backend.set(name, cleaned)
        self._forget(name)
        self._redactor.add_value(cleaned)
        now = utc_now()
        self._db.call(lambda s: s.merge(SecretMeta(name=name, source=source, updated_at=now)))
        log.info("secret_set", name=name, source=source)

    def delete(self, name: str) -> None:
        self.spec(name)
        self._backend.delete(name)
        self._forget(name)
        self._db.call(lambda s: s.query(SecretMeta).filter_by(name=name).delete())
        log.info("secret_deleted", name=name)

    def record_check(self, name: str, *, ok: bool, detail: str, latency_ms: int | None) -> None:
        self.spec(name)
        now = utc_now()

        def write(session: Session) -> None:
            meta = session.get(SecretMeta, name)
            if meta is None:
                meta = SecretMeta(name=name, source="env", updated_at=now)
                session.add(meta)
            meta.last_check_ok = ok
            meta.last_check_at = now
            meta.last_check_detail = self._redactor.redact(detail)[:300]
            meta.last_check_latency_ms = latency_ms

        self._db.call(write)

    def status(self) -> list[SecretStatus]:
        metas = {m.name: m for m in self._db.call(lambda s: list(s.scalars(select(SecretMeta))))}
        result: list[SecretStatus] = []
        for spec in CATALOG:
            meta = metas.get(spec.name)
            configured = self._backend.get(spec.name) is not None
            result.append(
                SecretStatus(
                    name=spec.name,
                    label=spec.label,
                    group=spec.group,
                    help=spec.help,
                    configured=configured,
                    source=meta.source if meta and configured else None,
                    updated_at=meta.updated_at if meta and configured else None,
                    last_check_ok=meta.last_check_ok if meta and configured else None,
                    last_check_at=meta.last_check_at if meta and configured else None,
                    last_check_detail=meta.last_check_detail if meta and configured else None,
                    last_check_latency_ms=meta.last_check_latency_ms
                    if meta and configured
                    else None,
                )
            )
        return result

    def import_dotenv(self, path: Path) -> list[str]:
        """Importe dans le trousseau les clés du `.env` qui n'y sont pas encore."""
        if not path.is_file():
            return []
        imported: list[str] = []
        for name, value in parse_dotenv(path, CATALOG_BY_NAME).items():
            if self._backend.get(name) is None:
                self.set(name, value, source="env")
                imported.append(name)
        if imported:
            log.info("secrets_imported_from_env", names=imported)
        return imported

    def ensure_local_key(self) -> None:
        """Clé de chiffrement locale (cookies, données sensibles au repos), générée une fois."""
        if self._backend.get(LOCAL_KEY_NAME) is None:
            self._backend.set(LOCAL_KEY_NAME, pysecrets.token_urlsafe(32))
            log.info("local_key_generated")

    def load_into_redactor(self) -> None:
        values = [self._backend.get(spec.name) for spec in CATALOG]
        values.append(self._backend.get(LOCAL_KEY_NAME))
        self._redactor.add_values(v for v in values if v)
