"""Assemblage des services du moteur, démarrés et arrêtés avec l'API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import anyio.to_thread
import httpx

from ojarvis import __version__
from ojarvis.config import EngineConfig
from ojarvis.core.clock import utc_now
from ojarvis.core.errors import UnavailableError
from ojarvis.core.logs import get_logger
from ojarvis.db.engine import Database
from ojarvis.db.migrate import upgrade_to_head
from ojarvis.events.bus import EventBus
from ojarvis.events.store import EventStore
from ojarvis.security.secrets import KeyringBackend, SecretBackend, SecretStore
from ojarvis.settings_store import SettingsStore
from ojarvis.tracing.tracer import TraceQueries, Tracer

log = get_logger(__name__)


class UnavailableBackend:
    """Trousseau absent : le moteur démarre quand même, l'interface affiche l'erreur."""

    name = "indisponible"

    def get(self, key: str) -> str | None:
        del key
        return None

    def set(self, key: str, value: str) -> None:
        del key, value
        raise UnavailableError("Trousseau du système indisponible.", code="keyring_unavailable")

    def delete(self, key: str) -> None:
        self.set(key, "")


@dataclass
class Services:
    config: EngineConfig
    db: Database
    bus: EventBus
    events: EventStore
    secrets: SecretStore
    settings: SettingsStore
    tracer: Tracer
    traces: TraceQueries
    http: httpx.AsyncClient
    started_at: datetime
    keyring_error: str | None
    imported_secrets: list[str]

    @classmethod
    async def start(
        cls,
        config: EngineConfig,
        *,
        secret_backend: SecretBackend | None = None,
        http_transport: httpx.AsyncBaseTransport | None = None,
    ) -> Services:
        config.paths.ensure()
        await anyio.to_thread.run_sync(upgrade_to_head, config.paths.db_path)
        db = Database(config.paths.db_path)
        events = EventStore(db)
        bus = EventBus(events.persist)

        keyring_error: str | None = None
        backend: SecretBackend
        if secret_backend is not None:
            backend = secret_backend
        else:
            try:
                backend = await anyio.to_thread.run_sync(KeyringBackend)
            except UnavailableError as exc:
                keyring_error = exc.message
                backend = UnavailableBackend()
                log.error("keyring_unavailable")
        secrets = SecretStore(db, backend)
        imported: list[str] = []
        if keyring_error is None:
            await anyio.to_thread.run_sync(secrets.ensure_local_key)
            if config.dotenv_path is not None:
                imported = await anyio.to_thread.run_sync(secrets.import_dotenv, config.dotenv_path)
        await anyio.to_thread.run_sync(secrets.load_into_redactor)

        services = cls(
            config=config,
            db=db,
            bus=bus,
            events=events,
            secrets=secrets,
            settings=SettingsStore(db),
            tracer=Tracer(db, bus),
            traces=TraceQueries(db),
            http=httpx.AsyncClient(timeout=httpx.Timeout(10.0), transport=http_transport),
            started_at=utc_now(),
            keyring_error=keyring_error,
            imported_secrets=imported,
        )
        await bus.publish(
            "engine.started",
            {
                "version": __version__,
                "dev_mode": config.dev_mode,
                "keyring": backend.name,
                "imported_secrets": imported,
            },
        )
        log.info("engine_started", version=__version__, keyring=backend.name)
        return services

    async def stop(self) -> None:
        await self.bus.publish("engine.stopping", {})
        await self.bus.drain()
        await self.http.aclose()
        self.db.dispose()
        log.info("engine_stopped")
