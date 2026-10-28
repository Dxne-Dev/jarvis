"""Assemblage des services du moteur, démarrés et arrêtés avec l'API."""

from __future__ import annotations

import asyncio
import functools
import os
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import anyio.to_thread
import httpx

from ojarvis import __version__
from ojarvis.agent.executor import PlanExecutor
from ojarvis.agent.loop import Agent
from ojarvis.agent.plans import PlanStore
from ojarvis.agent.review import CodeReviewer
from ojarvis.agents.orchestrator import Orchestrator
from ojarvis.agents.specialists import STARTERS
from ojarvis.anticipation.predictor import Predictor
from ojarvis.anticipation.repetition import RepetitionWatcher
from ojarvis.anticipation.service import AnticipationService
from ojarvis.anticipation.store import SuggestionStore
from ojarvis.audit.journal import AuditJournal
from ojarvis.automations.scheduler import AutomationScheduler
from ojarvis.automations.steps import AutomationSteps
from ojarvis.automations.store import AutomationStore
from ojarvis.briefing.service import BriefingService
from ojarvis.browser.proxy import GuardProxy
from ojarvis.browser.service import BrowserAccess
from ojarvis.browser.vault import CookieVault
from ojarvis.chat.service import ChatService
from ojarvis.config import EngineConfig
from ojarvis.context.engine import RELEVANCE_FLOOR, ContextEngine
from ojarvis.conversations.store import ConversationStore
from ojarvis.core.clock import local_timezone, utc_now
from ojarvis.core.errors import UnavailableError
from ojarvis.core.logs import get_logger
from ojarvis.db.engine import Database
from ojarvis.db.migrate import upgrade_to_head
from ojarvis.events.bus import Event, EventBus
from ojarvis.events.store import EventStore
from ojarvis.integrations.google import GoogleAccount, attach_agenda
from ojarvis.integrations.manager import IntegrationManager
from ojarvis.integrations.mcp_registry import McpRegistryService
from ojarvis.llm.catalog import Catalog
from ojarvis.llm.providers.base import Provider
from ojarvis.llm.providers.fake import FakeProvider, e2e_script
from ojarvis.llm.providers.registry import OllamaProvider, build_providers, discover_openrouter_free
from ojarvis.llm.router import ModelRouter, Route
from ojarvis.memory.embeddings import E5Embedder, Embedder
from ojarvis.memory.graph import GraphStore
from ojarvis.memory.store import MemoryStore
from ojarvis.notifications import Notifier
from ojarvis.permissions.gate import PermissionGate
from ojarvis.sandbox.runner import SandboxRunner
from ojarvis.security.secrets import (
    LOCAL_KEY_NAME,
    KeyringBackend,
    MemoryBackend,
    SecretBackend,
    SecretStore,
)
from ojarvis.settings_store import Preferences, SettingsStore
from ojarvis.shell.machine import MachineCard
from ojarvis.shell.servers import BackgroundSessions
from ojarvis.skills.runner import SkillRunner
from ojarvis.skills.service import SkillService
from ojarvis.skills.store import SkillStore
from ojarvis.telegram.bot import TelegramService
from ojarvis.tools.agents import agent_tools
from ojarvis.tools.automations import automation_tools
from ojarvis.tools.base import ToolContext, ToolRegistry
from ojarvis.tools.catalog import build_registry
from ojarvis.tools.code import ListCapabilities
from ojarvis.tools.desktop import desktop_tools
from ojarvis.tools.impasses import impasse_tools
from ojarvis.tools.integrations import integration_tools
from ojarvis.tools.machine import ReadMachineMap
from ojarvis.tools.mcp import mcp_tools
from ojarvis.tools.shell import LookAtPage, OpenShell, ProposeAdmin, RunCommand
from ojarvis.tools.skills import skill_tools
from ojarvis.tracing.tracer import TraceQueries, Tracer
from ojarvis.voice.service import VoiceService
from ojarvis.voice.simulated import simulated_voice
from ojarvis.voice.stt import GroqTranscriber
from ojarvis.workflows.engine import WorkflowEngine

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
class _Actions:
    """Ce qui permet à Jarvis d'agir et de s'organiser (assemblé à part, pour la lisibilité)."""

    journal: AuditJournal
    integrity_ok: bool
    guard: GuardProxy
    browser: BrowserAccess
    sandbox: SandboxRunner
    notifier: Notifier
    automations: AutomationStore
    workflows: WorkflowEngine
    scheduler: AutomationScheduler
    integrations: IntegrationManager
    tools: ToolRegistry
    skills: SkillService
    gate: PermissionGate
    plans: PlanStore
    executor: PlanExecutor


async def _assemble_actions(  # noqa: PLR0917 - un assemblage, pas une logique
    config: EngineConfig,
    db: Database,
    bus: EventBus,
    secrets: SecretStore,
    http: httpx.AsyncClient,
    router: ModelRouter,
    conversations: ConversationStore,
    prefs: Callable[[], Preferences],
) -> _Actions:
    # Jarvis agit : journal immuable vérifié au démarrage, outils derrière une seule porte.
    journal = AuditJournal(db, bus)
    integrity = await journal.verify()
    user_home = config.user_home or Path.home()
    vault = CookieVault(
        config.paths.data_dir / "navigateur" / "coffre.bin",
        lambda: secrets.get(LOCAL_KEY_NAME),
    )
    # Toute lecture du web (navigateur, pages) passe par ce proxy : adresses publiques.
    guard = GuardProxy(allowed_hosts=config.tool_private_hosts)
    await guard.start()
    browser = BrowserAccess(
        db=db,
        vault=vault,
        journal=journal,
        bus=bus,
        home=user_home,
        allowed_hosts=config.tool_private_hosts,
        proxy=guard,
    )
    await browser.start()
    sandbox = SandboxRunner()
    # Jarvis s'organise : automatisations, workflows persistés, notifications.
    notifier = Notifier(bus)
    automations = AutomationStore(db, local_timezone)
    workflows = WorkflowEngine(db, bus)
    scheduler = AutomationScheduler(store=automations, workflows=workflows, bus=bus)
    integrations = IntegrationManager(secrets.get)
    servers = BackgroundSessions()  # les serveurs lancés par le mode shell
    tools = build_registry(
        browser.session,
        [
            *automation_tools(automations, scheduler),
            *integration_tools(integrations),
            *desktop_tools(router, lambda: prefs().screen_vision),
            # Proposés seulement en mode shell ; journaux et captures dans l'état du moteur.
            RunCommand(user_home, log_dir=config.paths.state_dir / "shell", sessions=servers),
            LookAtPage(
                router,
                lambda: prefs().screen_vision,
                servers,
                capture_dir=config.paths.state_dir / "shell" / "captures",
            ),
            OpenShell(user_home),  # « passe en mode shell » : ouvre un terminal
            ProposeAdmin(),  # sudo : proposé par Jarvis, lancé par toi
        ],
    )
    # Jarvis s'étend : les skills actifs apportent leurs outils, testés en bac à sable.
    skills = SkillService(SkillStore(db), SkillRunner(sandbox), tools, bus)
    for tool in skill_tools(skills):
        tools.register(tool)
    capabilities = tools.get("lister_capacites")
    if isinstance(capabilities, ListCapabilities):
        capabilities.add_section("Skills", skills.capabilities)
    await skills.start()

    def tool_context() -> ToolContext:
        return ToolContext(
            http=http,
            secret=secrets.get,
            home=user_home,
            sandbox=sandbox,
            allowed_private_hosts=config.tool_private_hosts,
            fetch_proxy=f"http://127.0.0.1:{guard.port}",
        )

    gate = PermissionGate(
        tools, journal, tool_context, os_control=lambda: prefs().os_control_enabled
    )
    plans = PlanStore(db, gate)
    executor = PlanExecutor(
        plans=plans,
        gate=gate,
        journal=journal,
        router=router,
        conversations=conversations,
        bus=bus,
    )
    return _Actions(
        journal=journal,
        integrity_ok=integrity.ok,
        guard=guard,
        browser=browser,
        sandbox=sandbox,
        notifier=notifier,
        automations=automations,
        workflows=workflows,
        scheduler=scheduler,
        integrations=integrations,
        tools=tools,
        skills=skills,
        gate=gate,
        plans=plans,
        executor=executor,
    )


def _assemble_anticipation(
    chat: ChatService,
    conversations: ConversationStore,
    graph: GraphStore,
    *,
    db: Database,
    bus: EventBus,
    embedder: Embedder,
) -> AnticipationService:
    """Apprendre de tes demandes répétées, anticiper d'après tes habitudes (lecture seule)."""
    store = SuggestionStore(db, bus)
    return AnticipationService(
        store=store,
        watcher=RepetitionWatcher(
            conversations, store, embedder_id=embedder.model_id, timezone=local_timezone
        ),
        predictor=Predictor(graph, store),
        chat=chat,
        conversations=conversations,
        bus=bus,
    )


async def _assemble_memory(
    db: Database, bus: EventBus, embedder: Embedder
) -> tuple[MemoryStore, ConversationStore, GraphStore, ContextEngine]:
    """Mémoire (faits, conversations, graphe) et moteur de contexte qui y puise."""
    memory = MemoryStore(db, embedder, bus)
    await memory.start()
    conversations = ConversationStore(db, embedder)
    await conversations.start()
    graph = GraphStore(db, bus)
    context = ContextEngine(memory, conversations, embedder_id=embedder.model_id, graph=graph)
    return memory, conversations, graph, context


def _memory_tools(
    acts: _Actions, memory: MemoryStore, embedder: Embedder, home: Path
) -> MachineCard:
    """Les outils qui ont besoin de la mémoire (elle n'existe qu'ici) : les impasses du mode
    shell, et la carte de la machine, relevée en lecture seule."""
    floor = RELEVANCE_FLOOR.get(embedder.model_id, 0.5)
    for tool in impasse_tools(memory, floor=floor):
        acts.tools.register(tool)
    machine = MachineCard(memory, acts.journal, home)
    acts.tools.register(ReadMachineMap(machine))
    return machine


def relay_policy(prefs: Preferences) -> tuple[Route, int] | None:
    """Le relais du profil « Tout Meta » : (modèle de relais, échecs avant de l'appeler)."""
    if prefs.model_profile != "meta" or prefs.relay_after == 0:
        return None
    provider, _, model = prefs.relay_model.partition("/")
    return Route(provider, model, thinking=True), prefs.relay_after


def _build_router(
    providers: dict[str, Provider],
    catalog: Catalog,
    *,
    bus: EventBus,
    tracer: Tracer,
    holder: dict[str, Preferences],
    http: httpx.AsyncClient,
) -> ModelRouter:
    ollama = providers.get("ollama")
    return ModelRouter(
        providers,
        catalog,
        bus=bus,
        tracer=tracer,
        overrides=lambda: holder["value"].routing,
        profile=lambda: holder["value"].model_profile,
        # Avant une demande « locale seulement », au plus une fois par minute.
        refresh_local=(
            functools.partial(ollama.refresh, http) if isinstance(ollama, OllamaProvider) else None
        ),
    )


async def _assemble_agents(
    acts: _Actions,
    core: Agent,
    *,
    router: ModelRouter,
    db: Database,
    bus: EventBus,
    tracer: Tracer,
) -> Orchestrator:
    """Les agents (dev, recherche, coach) passent par le même cœur : même porte, mêmes plans."""
    orchestrator = Orchestrator(
        {a.name: a(router=router, core=core) for a in STARTERS},
        db=db,
        bus=bus,
        tracer=tracer,
    )
    for tool in agent_tools(orchestrator):
        acts.tools.register(tool)
    await orchestrator.recover()
    return orchestrator


async def _assemble_mcp(
    acts: _Actions,
    *,
    http: httpx.AsyncClient,
    db: Database,
    backend: SecretBackend,
    config: EngineConfig,
    bus: EventBus,
) -> McpRegistryService:
    """Jarvis s'étend aussi par les serveurs MCP du registre officiel (installés isolés)."""
    mcp = McpRegistryService(
        http=http,
        db=db,
        manager=acts.integrations,
        backend=backend,
        data_dir=config.paths.data_dir,
        bus=bus,
    )
    for tool in mcp_tools(mcp):
        acts.tools.register(tool)
    capabilities = acts.tools.get("lister_capacites")
    if isinstance(capabilities, ListCapabilities):
        capabilities.add_section("Serveurs MCP installés", mcp.capabilities)
    await mcp.start()
    return mcp


async def _assemble_remote(  # noqa: PLR0917 - un assemblage, pas une logique
    acts: _Actions,
    http: httpx.AsyncClient,
    secrets: SecretStore,
    backend: SecretBackend,
    bus: EventBus,
    chat: ChatService,
) -> tuple[GoogleAccount, TelegramService]:
    """Ce qui relie Jarvis à tes comptes : Google (agenda) et Telegram (téléphone)."""
    google = GoogleAccount(http=http, secret=secrets.get, backend=backend, bus=bus)
    await anyio.to_thread.run_sync(google.load_into_redactor)

    async def google_connected() -> None:
        await attach_agenda(google, acts.integrations, http)

    google.on_connected = google_connected
    telegram = TelegramService(
        http=http,
        secret=secrets.get,
        chat=chat,
        plans=acts.plans,
        executor=acts.executor,
        notifier=acts.notifier,
        bus=bus,
        transcriber=GroqTranscriber(lambda: secrets.get("GROQ_API_KEY"), http),
    )
    return google, telegram


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
    journal: AuditJournal
    tools: ToolRegistry
    gate: PermissionGate
    plans: PlanStore
    executor: PlanExecutor
    browser: BrowserAccess
    sandbox: SandboxRunner
    guard: GuardProxy
    notifier: Notifier
    automations: AutomationStore
    workflows: WorkflowEngine
    scheduler: AutomationScheduler
    telegram: TelegramService
    integrations: IntegrationManager
    google: GoogleAccount
    skills: SkillService
    mcp: McpRegistryService
    orchestrator: Orchestrator
    graph: GraphStore
    anticipation: AnticipationService
    machine: MachineCard
    briefing: BriefingService = field(init=False)
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
        router = _build_router(providers, catalog, bus=bus, tracer=tracer, holder=holder, http=http)
        embedder = embedder or E5Embedder(
            config.paths.cache_dir / "models" / "multilingual-e5-small"
        )
        memory, conversations, graph, context = await _assemble_memory(db, bus, embedder)

        acts = await _assemble_actions(
            config, db, bus, secrets, http, router, conversations, lambda: holder["value"]
        )
        machine = _memory_tools(acts, memory, embedder, config.user_home or Path.home())
        core = Agent(
            gate=acts.gate,
            plans=acts.plans,
            bus=bus,
            executor=acts.executor,
            reviewer=CodeReviewer(router),
        )
        chat = ChatService(
            conversations=conversations,
            memory=memory,
            context=context,
            router=router,
            tracer=tracer,
            bus=bus,
            learn=preferences.learn_from_conversations,
            agent=core,
            graph=graph,
            relay=lambda: relay_policy(holder["value"]),
            machine=machine,
        )
        orchestrator = await _assemble_agents(
            acts, core, router=router, db=db, bus=bus, tracer=tracer
        )
        google, telegram = await _assemble_remote(acts, http, secrets, backend, bus, chat)
        mcp = await _assemble_mcp(acts, http=http, db=db, backend=backend, config=config, bus=bus)
        anticipation = _assemble_anticipation(
            chat, conversations, graph, db=db, bus=bus, embedder=embedder
        )
        anticipation.start(periodic=discover)

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
            journal=acts.journal,
            tools=acts.tools,
            gate=acts.gate,
            plans=acts.plans,
            executor=acts.executor,
            browser=acts.browser,
            sandbox=acts.sandbox,
            guard=acts.guard,
            notifier=acts.notifier,
            automations=acts.automations,
            workflows=acts.workflows,
            scheduler=acts.scheduler,
            telegram=telegram,
            integrations=acts.integrations,
            google=google,
            skills=acts.skills,
            mcp=mcp,
            orchestrator=orchestrator,
            graph=graph,
            anticipation=anticipation,
            machine=machine,
        )
        services._holder = holder
        await acts.executor.recover()
        acts.workflows.handlers.update(
            AutomationSteps(store=acts.automations, chat=chat, notifier=acts.notifier).handlers()
        )
        services.briefing = BriefingService(
            settings=settings,
            workflows=acts.workflows,
            router=router,
            conversations=conversations,
            automations=acts.automations,
            integrations=acts.integrations,
            google=google,
            voice=voice,
            notifier=acts.notifier,
            bus=bus,
            http=http,
        )
        acts.workflows.handlers.update(services.briefing.handlers())
        await acts.workflows.start()
        await acts.scheduler.start()
        # Telegram : seulement pour un vrai lancement (un banc d'essai ou un test ne doit pas
        # répondre à tes messages à la place de l'app).
        if discover or os.environ.get("OJARVIS_TELEGRAM") == "1":
            await services.telegram.start()
            # Les serveurs MCP configurés démarrent en arrière-plan (Docker, réseau).
            services.spawn(acts.integrations.start_configured())
            if google.connected:
                services.spawn(services._attach_agenda())
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
                "audit_ok": acts.integrity_ok,
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

    async def _attach_agenda(self) -> None:
        try:
            await attach_agenda(self.google, self.integrations, self.http)
        except Exception:
            log.warning("agenda_attach_failed")

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
        # La voix suit aussi le profil : couper « Tout Meta » cesse tout de suite d'envoyer ta
        # voix à Meta.
        voice_keys = [
            k
            for k in Preferences.model_fields
            if k.startswith(("voice_", "wake_")) or k == "model_profile"
        ]
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
        if not await self._start_memory():
            return
        await self.bus.publish("engine.ready", {"embeddings": self.embedder.status}, persist=False)

    async def _start_memory(self) -> bool:
        """Charge le modèle d'embeddings (téléchargé s'il manque) puis démarre la mémoire."""
        if not isinstance(self.embedder, E5Embedder) or self.embedder.status == "prêt":
            return True
        try:
            await self.embedder.ensure(self.http)
        except Exception:
            log.exception("embedding_model_unavailable")
            return False
        await self.memory.start()
        await self.conversations.start()
        return True

    @property
    def models_dir(self) -> Path:
        return self.config.paths.cache_dir / "models"

    def model_states(self) -> dict[str, str]:
        """État vivant de chaque modèle local (téléchargement en cours, erreur…)."""
        states = dict(self.voice.status.models)
        states["memoire"] = self.embedder.status
        return states

    def retry_local_models(self) -> None:
        """Relance, en tâche de fond, ce qui manque : la voix si elle est activée, la mémoire."""
        if self.preferences.voice_enabled and self.voice.status.state == "error":
            self.spawn(self.voice.apply(self.preferences))
        if self.embedder.status != "prêt":
            self.spawn(self._start_memory_and_announce())

    async def _start_memory_and_announce(self) -> None:
        if await self._start_memory():
            await self.bus.publish(
                "engine.ready", {"embeddings": self.embedder.status}, persist=False
            )

    async def stop(self) -> None:
        await self.bus.publish("engine.stopping", {})
        await self.voice.close()
        await self.chat.close()
        await self.anticipation.close()
        await self.orchestrator.close()
        await self.telegram.close()
        await self.integrations.close()
        await self.google.close()
        await self.scheduler.close()
        await self.workflows.close()
        await self.executor.close()
        await self.browser.close()
        await self.guard.close()
        for task in list(self.background):
            task.cancel()
        await asyncio.gather(*list(self.background), return_exceptions=True)
        await self.bus.drain()
        await self.http.aclose()
        self.db.dispose()
        log.info("engine_stopped")
