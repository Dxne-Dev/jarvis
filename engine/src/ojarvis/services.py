"""Assemblage des services du moteur, démarrés et arrêtés avec l'API."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Coroutine
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import anyio.to_thread
import httpx

from ojarvis import __version__
from ojarvis.chat.service import ChatService
from ojarvis.config import EngineConfig
from ojarvis.context.engine import ContextEngine
from ojarvis.conversations.store import ConversationStore
from ojarvis.core.clock import utc_now
from ojarvis.core.errors import UnavailableError
from ojarvis.core.logs import get_logger
from ojarvis.db.engine import Database
from ojarvis.db.migrate import upgrade_to_head
from ojarvis.events.bus import Event, EventBus
from ojarvis.events.store import EventStore
from ojarvis.llm.catalog import Catalog
from ojarvis.llm.providers.base import Provider
from ojarvis.llm.providers.fake import FakeProvider, e2e_script
from ojarvis.llm.providers.registry import OllamaProvider, build_providers, discover_openrouter_free
from ojarvis.llm.router import ModelRouter
from ojarvis.memory.embeddings import E5Embedder, Embedder
from ojarvis.memory.store import MemoryStore
from ojarvis.security.secrets import KeyringBackend, MemoryBackend, SecretBackend, SecretStore
from ojarvis.settings_store import Preferences, SettingsStore
from ojarvis.tracing.tracer import TraceQueries, Tracer
from ojarvis.voice.service import VoiceService
from ojarvis.voice.simulated import simulated_voice

log = get_logger(__name__)

#: Modèle local de repli (voir la politique du routeur) et fréquence maximale de préchargement.
LOCAL_MODEL = "ministral-3:3b"
LOCAL_PRELOAD_EVERY_S = 300.0


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


async def _open_secrets(
    config: EngineConfig, db: Database, secret_backend: SecretBackend | None
) -> tuple[SecretStore, SecretBackend, str | None, list[str]]:
    """Trousseau du système (ou de test), clé locale, import des clés présentes dans .env."""
    keyring_error: str | None = None
    backend: SecretBackend
    if secret_backend is not None:
        backend = secret_backend
    elif config.dev_mode and os.environ.get("OJARVIS_MEMORY_KEYRING") == "1":
        # Tests de bout en bout : trousseau en mémoire, jamais le vrai, jamais sur disque.
        backend = MemoryBackend()
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
    return secrets, backend, keyring_error, imported


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
    preferences: Preferences
    catalog: Catalog
    providers: dict[str, Provider]
    router: ModelRouter
    embedder: Embedder
    memory: MemoryStore
    conversations: ConversationStore
    context: ContextEngine
    chat: ChatService
    voice: VoiceService
    background: set[asyncio.Task[None]] = field(default_factory=set)

    @classmethod
    async def start(
        cls,
        config: EngineConfig,
        *,
        secret_backend: SecretBackend | None = None,
        http_transport: httpx.AsyncBaseTransport | None = None,
        embedder: Embedder | None = None,
        providers: dict[str, Provider] | None = None,
        discover: bool = True,
    ) -> Services:
        config.paths.ensure()
        await anyio.to_thread.run_sync(upgrade_to_head, config.paths.db_path)
        db = Database(config.paths.db_path)
        events = EventStore(db)
        bus = EventBus(events.persist)

        secrets, backend, keyring_error, imported = await _open_secrets(config, db, secret_backend)

        settings = SettingsStore(db)
        preferences = await settings.get()
        tracer = Tracer(db, bus)
        http = httpx.AsyncClient(timeout=httpx.Timeout(10.0), transport=http_transport)
        catalog = Catalog()
        if providers is None and config.dev_mode and os.environ.get("OJARVIS_FAKE_LLM") == "1":
            # Tests de bout en bout : réponses prévisibles, aucun appel à un vrai modèle.
            providers = {"deepseek": FakeProvider("deepseek", script=e2e_script, delay_s=0.05)}
        providers = providers if providers is not None else build_providers(secrets)
        holder: dict[str, Preferences] = {"value": preferences}
        router = ModelRouter(
            providers, catalog, bus=bus, tracer=tracer, overrides=lambda: holder["value"].routing
        )
        embedder = embedder or E5Embedder(
            config.paths.cache_dir / "models" / "multilingual-e5-small"
        )
        memory = MemoryStore(db, embedder, bus)
        await memory.start()
        conversations = ConversationStore(db, embedder)
        await conversations.start()
        context = ContextEngine(memory, conversations, embedder_id=embedder.model_id)
        chat = ChatService(
            conversations=conversations,
            memory=memory,
            context=context,
            router=router,
            tracer=tracer,
            bus=bus,
            learn=preferences.learn_from_conversations,
        )

        # Audio réel seulement pour un vrai lancement : jamais dans les tests ni en CI.
        # Tests de bout en bout : audio simulé (pas de micro, de haut-parleur ni de modèle).
        simulated = config.dev_mode and os.environ.get("OJARVIS_FAKE_AUDIO") == "1"
        audio = simulated or (
            discover
            and os.environ.get("OJARVIS_SKIP_WARMUP") != "1"
            and os.environ.get("OJARVIS_NO_AUDIO") != "1"
        )
        voice = VoiceService(
            models_dir=config.paths.cache_dir / "models",
            http=http,
            bus=bus,
            tracer=tracer,
            chat=chat,
            secrets=secrets,
            preferences=lambda: holder["value"],
            audio=audio,
            **(simulated_voice() if simulated else {}),
        )

        services = cls(
            config=config,
            db=db,
            bus=bus,
            events=events,
            secrets=secrets,
            settings=settings,
            tracer=tracer,
            traces=TraceQueries(db),
            http=http,
            started_at=utc_now(),
            keyring_error=keyring_error,
            imported_secrets=imported,
            preferences=preferences,
            catalog=catalog,
            providers=providers,
            router=router,
            embedder=embedder,
            memory=memory,
            conversations=conversations,
            context=context,
            chat=chat,
            voice=voice,
        )
        services._holder = holder
        # OJARVIS_SKIP_WARMUP=1 : aucun accès réseau ni téléchargement au démarrage (tests).
        if discover and os.environ.get("OJARVIS_SKIP_WARMUP") != "1":
            services.spawn(services._warm_up())
            bus.subscribe("llm.provider_degraded", services._preload_local_model)
        services.spawn(voice.start())
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

    _holder: dict[str, Preferences] = field(default_factory=dict)
    _last_local_preload: float = -LOCAL_PRELOAD_EVERY_S

    async def _preload_local_model(self, event: Event) -> None:
        """Un fournisseur en ligne tombe : on charge le modèle local en mémoire, en avance.

        Son premier chargement prend de 13 à 50 s sur cette machine ; s'il est déjà en
        mémoire quand le repli arrive, la réponse part tout de suite.
        """
        ollama = self.providers.get("ollama")
        if event.payload.get("provider") == "ollama" or not isinstance(ollama, OllamaProvider):
            return
        now = time.monotonic()
        if now - self._last_local_preload < LOCAL_PRELOAD_EVERY_S:
            return
        self._last_local_preload = now
        await ollama.refresh(self.http)
        if LOCAL_MODEL in ollama.models:
            log.info("local_model_preload", model=LOCAL_MODEL)
            await ollama.warm_up(self.http, LOCAL_MODEL)

    def spawn(self, coroutine: Coroutine[Any, Any, None]) -> None:
        """Tâche de fond suivie (annulée proprement à l'arrêt)."""
        task = asyncio.create_task(coroutine)
        self.background.add(task)
        task.add_done_callback(self.background.discard)

    def set_preferences(self, preferences: Preferences) -> None:
        previous = self.preferences
        self.preferences = preferences
        self._holder["value"] = preferences
        self.chat.learn = preferences.learn_from_conversations
        voice_keys = [k for k in Preferences.model_fields if k.startswith(("voice_", "wake_"))]
        if any(getattr(previous, k) != getattr(preferences, k) for k in voice_keys):
            self.spawn(self.voice.apply(preferences))

    async def _warm_up(self) -> None:
        """Au démarrage, sans bloquer : modèle d'embeddings, modèles gratuits, Ollama."""
        ollama = self.providers.get("ollama")
        if isinstance(ollama, OllamaProvider):
            await ollama.refresh(self.http, force=True)
        if self.providers.get("openrouter") is not None:
            count = await discover_openrouter_free(self.catalog, self.http)
            log.info("openrouter_free_models", count=count)
        if isinstance(self.embedder, E5Embedder):
            try:
                await self.embedder.ensure(self.http)
            except Exception:
                log.exception("embedding_model_unavailable")
                return
            await self.memory.start()
            await self.conversations.start()
        await self.bus.publish("engine.ready", {"embeddings": self.embedder.status}, persist=False)

    async def stop(self) -> None:
        await self.bus.publish("engine.stopping", {})
        await self.voice.close()
        await self.chat.close()
        for task in list(self.background):
            task.cancel()
        await asyncio.gather(*list(self.background), return_exceptions=True)
        await self.bus.drain()
        await self.http.aclose()
        self.db.dispose()
        log.info("engine_stopped")
