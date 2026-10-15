"""Les serveurs MCP du registre : chercher, essayer isolé, installer, désactiver, retirer.

Installer un serveur, c'est donner de nouveaux outils à Jarvis : niveau 3, double
confirmation, journal. L'essai le lance isolé (Docker, sinon bubblewrap) et liste ses outils
avec leur niveau ; ensuite, chaque appel passe par la porte avec le niveau de l'outil.

Ses clés (réglages marqués secrets par l'éditeur) vont au trousseau et au filtre des logs ;
elles ne viennent jamais du modèle et ne lui sont jamais montrées.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import shutil
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import anyio.to_thread
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ojarvis.core.clock import utc_now
from ojarvis.core.errors import ConflictError, InvalidInputError, NotFoundError, UnavailableError
from ojarvis.core.logs import get_logger
from ojarvis.db.engine import Database
from ojarvis.db.models import McpServer
from ojarvis.events.bus import EventBus
from ojarvis.integrations import registry
from ojarvis.integrations.connection import McpConnection
from ojarvis.integrations.manager import SERVERS, CustomServer, IntegrationManager
from ojarvis.integrations.registry import InstallOption, RegistryEntry, RegistryError, Runtimes
from ojarvis.sandbox.runner import bubblewrap_available, docker_available
from ojarvis.security.redaction import REDACTOR, Redactor
from ojarvis.security.secrets import SecretBackend
from ojarvis.tools.guards import check_public_url

log = get_logger(__name__)

#: Ce qu'un lanceur rend : la cible de `mcp.Client` pour (façon de lancer, identifiant, réglages).
Launcher = Callable[[InstallOption, str, dict[str, str]], Any]


async def detect_runtimes() -> Runtimes:
    docker = shutil.which("docker") if await docker_available() else None
    bwrap = shutil.which("bwrap") if await bubblewrap_available() else None
    return Runtimes(docker=docker, bwrap=bwrap, npx=shutil.which("npx"), uvx=shutil.which("uvx"))


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    tools: list[dict[str, Any]]
    error: str | None
    runner: str
    seconds: float


@dataclass(frozen=True)
class InstalledServer:
    id: str
    registry_name: str
    title: str
    description: str
    version: str
    option: InstallOption
    variables: dict[str, str]
    secret_names: list[str]
    tools: list[dict[str, Any]]
    enabled: bool
    installed_at: datetime
    updated_at: datetime = field(compare=False)

    @property
    def label(self) -> str:
        return f"« {self.title} » v{self.version}"


def _record(row: McpServer) -> InstalledServer:
    return InstalledServer(
        id=row.id,
        registry_name=row.registry_name,
        title=row.title,
        description=row.description,
        version=row.version,
        option=InstallOption.from_json(row.option),
        variables={str(k): str(v) for k, v in row.variables.items()},
        secret_names=[str(n) for n in row.secrets.get("names", [])],
        tools=list(row.tools),
        enabled=row.enabled,
        installed_at=row.installed_at,
        updated_at=row.updated_at,
    )


def local_id(registry_name: str, taken: set[str]) -> str:
    """« io.github.cyanheads/wikipedia-mcp-server » → « wikipedia-mcp-server »."""
    base = re.sub(r"[^a-z0-9]+", "-", registry_name.rsplit("/", 1)[-1].lower()).strip("-")
    base = (base or "serveur")[:34].strip("-")
    candidate, n = base, 2
    while candidate in taken or candidate in SERVERS:
        candidate, n = f"{base}-{n}", n + 1
    return candidate


def _clean(value: str, name: str) -> str:
    cleaned = value.strip()
    if len(cleaned) > 4096 or any(c in cleaned for c in "\r\n\0"):
        raise InvalidInputError(f"Valeur invalide pour {name}.")
    return cleaned


def environment(
    option: InstallOption, variables: Mapping[str, str], secrets: Mapping[str, str]
) -> dict[str, str]:
    """Les réglages du serveur : imposés par l'éditeur, les tiens, ses valeurs par défaut."""
    declared = {v.name: v for v in option.env}
    unknown = [n for n in [*variables, *secrets] if n not in declared]
    if unknown:
        raise InvalidInputError(f"Réglage inconnu pour ce serveur : {', '.join(unknown)}.")
    misplaced = [n for n in variables if declared[n].secret]
    if misplaced:
        raise InvalidInputError(
            f"Ces réglages sont des clés, à saisir à part : {', '.join(misplaced)}."
        )
    env: dict[str, str] = {}
    for var in option.env:
        if var.value is not None:
            env[var.name] = var.value
            continue
        given = secrets.get(var.name) if var.secret else variables.get(var.name)
        value = _clean(given, var.name) if given else (var.default or "")
        if value:
            env[var.name] = value
        elif var.required:
            kind = "La clé" if var.secret else "Le réglage"
            raise InvalidInputError(f"{kind} {var.name} est obligatoire pour ce serveur.")
    return env


class McpRegistryService:
    def __init__(
        self,
        *,
        http: httpx.AsyncClient,
        db: Database,
        manager: IntegrationManager,
        backend: SecretBackend,
        data_dir: Path,
        bus: EventBus,
        runtimes: Callable[[], Awaitable[Runtimes]] = detect_runtimes,
        launcher: Launcher | None = None,
        redactor: Redactor = REDACTOR,
    ) -> None:
        self._http = http
        self._db = db
        self._manager = manager
        self._backend = backend
        self._data_dir = data_dir
        self._bus = bus
        self._runtimes = runtimes
        self._launcher = launcher
        self._redactor = redactor
        self._entries: dict[tuple[str, str], RegistryEntry] = {}
        #: Dernier état connu de Docker et de bubblewrap (pour décrire sans attendre).
        self.last_runtimes: Runtimes | None = None
        self._installed: dict[str, InstalledServer] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ démarrage

    async def start(self) -> None:
        rows = await self._db.run(lambda s: [_record(r) for r in s.scalars(select(McpServer))])
        for server in rows:
            self._installed[server.id] = server
            values = await anyio.to_thread.run_sync(self._secret_values, server)
            self._redactor.add_values(v for v in values.values() if v)
            if server.enabled:
                await self._attach(server)

    # ------------------------------------------------------------------ registre

    async def search(self, query: str, *, limit: int = 20) -> list[RegistryEntry]:
        entries = await registry.search(self._http, query, limit=limit)
        for entry in entries:
            self._entries[(entry.name, entry.version)] = entry
        return entries

    async def entry(self, name: str, version: str) -> RegistryEntry:
        cached = self._entries.get((name, version))
        if cached is not None:
            return cached
        entry = await registry.fetch(self._http, name, version)
        self._entries[(entry.name, entry.version)] = entry
        return entry

    def cached(self, name: str, version: str) -> RegistryEntry | None:
        return self._entries.get((name, version))

    async def runtimes(self) -> Runtimes:
        self.last_runtimes = await self._runtimes()
        return self.last_runtimes

    async def plan(self, name: str, version: str) -> tuple[RegistryEntry, InstallOption, Runtimes]:
        """La fiche, et la façon de lancer le serveur ici (sinon une erreur claire)."""
        try:
            entry = await self.entry(name, version)
        except RegistryError as exc:
            raise UnavailableError(str(exc).capitalize() + ".") from exc
        runtimes = await self.runtimes()
        option = entry.best(runtimes)
        if option is None:
            raise UnavailableError(
                f"« {entry.title} » ne peut pas être installé : {entry.why_not(runtimes)}."
            )
        if option.kind == "remote":
            await check_public_url(option.identifier)
        return entry, option, runtimes

    # ------------------------------------------------------------------ essai et installation

    async def probe(
        self,
        name: str,
        version: str,
        variables: Mapping[str, str] | None = None,
        secrets: Mapping[str, str] | None = None,
    ) -> ProbeResult:
        """Lance le serveur isolé, liste ses outils et leur niveau, puis l'arrête."""
        entry, option, runtimes = await self.plan(name, version)
        env = environment(option, variables or {}, secrets or {})
        server_id = self._existing_id(entry.name) or local_id(entry.name, set(self._installed))
        connection = McpConnection(
            f"essai de {entry.title}", self._target(option, server_id, env, runtimes)
        )
        started = time.perf_counter()
        try:
            state = await connection.start()
            # Lu avant la fermeture, qui remet l'état à « arrêté ».
            ready, error = state.status == "prêt", state.error
            tools = [
                {"name": t.name, "description": t.description, "level": int(t.level)}
                for t in sorted(state.tools.values(), key=lambda t: t.name)
            ]
        finally:
            await connection.close()
        seconds = round(time.perf_counter() - started, 1)
        runner = runtimes.runner(option) if self._launcher is None else "essai"
        if not ready:
            return ProbeResult(False, [], error or "le serveur ne démarre pas", runner, seconds)
        return ProbeResult(True, tools, None, runner, seconds)

    async def install(
        self,
        name: str,
        version: str,
        variables: Mapping[str, str] | None = None,
        secrets: Mapping[str, str] | None = None,
    ) -> InstalledServer:
        """Essai isolé ; s'il réussit, le serveur est enregistré et ses outils deviennent
        utilisables (chacun à son niveau)."""
        async with self._lock:
            entry, option, _ = await self.plan(name, version)
            if self._existing_id(entry.name) is not None:
                raise ConflictError(f"« {entry.title} » est déjà installé : retire-le d'abord.")
            result = await self.probe(name, version, variables, secrets)
            if not result.ok:
                raise UnavailableError(f"L'essai de « {entry.title} » a échoué : {result.error}.")
            server_id = local_id(entry.name, set(self._installed))
            secret_names = [v.name for v in option.env if v.secret and (secrets or {}).get(v.name)]
            plain = {k: _clean(v, k) for k, v in (variables or {}).items() if v}
            await anyio.to_thread.run_sync(
                self._store_secrets, server_id, secrets or {}, secret_names
            )
            now = utc_now()
            row = McpServer(
                id=server_id,
                registry_name=entry.name,
                title=entry.title,
                description=entry.description,
                version=entry.version,
                option=option.to_json(),
                variables=plain,
                secrets={"names": secret_names},
                tools=result.tools,
                enabled=True,
                installed_at=now,
                updated_at=now,
            )

            def write(session: Session) -> InstalledServer:
                session.add(row)
                session.flush()
                return _record(row)

            server = await self._db.run(write)
            self._installed[server.id] = server
            await self._attach(server)
        # Démarré tout de suite : ses outils et leurs niveaux sont connus dès le premier appel.
        with contextlib.suppress(Exception):
            await self._manager.ensure(server.id)
        log.info("mcp_installed", server=server.id, version=server.version, kind=option.kind)
        await self._publish("mcp.installed", server)
        return server

    async def set_enabled(self, server_id: str, enabled: bool) -> InstalledServer:
        server = self.get(server_id)
        now = utc_now()

        def write(session: Session) -> InstalledServer:
            row = session.get(McpServer, server_id)
            if row is None:
                raise NotFoundError("Serveur MCP introuvable.")
            row.enabled = enabled
            row.updated_at = now
            return _record(row)

        server = await self._db.run(write)
        self._installed[server_id] = server
        if enabled:
            await self._attach(server)
        else:
            await self._manager.remove_custom(server_id)
        await self._publish("mcp.changed", server)
        return server

    async def uninstall(self, server_id: str) -> InstalledServer:
        server = self.get(server_id)
        await self._manager.remove_custom(server_id)

        def write(session: Session) -> None:
            row = session.get(McpServer, server_id)
            if row is not None:
                session.delete(row)

        await self._db.run(write)
        await anyio.to_thread.run_sync(self._forget_secrets, server)
        await self._remove_storage(server_id)
        self._installed.pop(server_id, None)
        log.info("mcp_uninstalled", server=server_id)
        await self._publish("mcp.uninstalled", server)
        return server

    def get(self, server_id: str) -> InstalledServer:
        server = self._installed.get(server_id)
        if server is None:
            raise NotFoundError("Serveur MCP introuvable.")
        return server

    def installed(self) -> list[InstalledServer]:
        return sorted(self._installed.values(), key=lambda s: s.title.lower())

    def status(self, server_id: str) -> dict[str, Any]:
        return self._manager.custom_status(server_id)

    def capabilities(self) -> list[str]:
        """Pour « lister_capacites » : les serveurs installés et leur état."""
        return [
            f"- {s.id} : {s.title} v{s.version} ({'actif' if s.enabled else 'désactivé'}) — "
            f'{s.description[:160]} ; outils via integrations_outils(serveur="{s.id}")'
            for s in self.installed()
        ]

    # ------------------------------------------------------------------ interne

    def _existing_id(self, registry_name: str) -> str | None:
        found = [s.id for s in self._installed.values() if s.registry_name == registry_name]
        return found[0] if found else None

    def _target(
        self, option: InstallOption, server_id: str, env: dict[str, str], runtimes: Runtimes
    ) -> Callable[[], Any]:
        if self._launcher is not None:
            launcher = self._launcher
            return lambda: launcher(option, server_id, env)
        if option.kind == "remote":
            return lambda: registry.remote_target(option)
        if runtimes.docker is not None:
            docker = runtimes.docker
            return lambda: registry.docker_target(option, server_id, env, docker=docker)
        home = self._data_dir / "mcp" / server_id
        return lambda: registry.bubblewrap_target(option, home, env, runtimes=runtimes)

    async def _attach(self, server: InstalledServer) -> None:
        """Le serveur rejoint les intégrations ; il démarre au premier usage."""
        runtimes = await self._runtimes()
        values = await anyio.to_thread.run_sync(self._secret_values, server)
        env = environment(server.option, server.variables, values)
        where = server.option.where
        await self._manager.add_custom(
            CustomServer(
                name=server.id,
                label=server.title,
                about=server.description[:160] or server.title,
                target=self._target(server.option, server.id, env, runtimes),
                detail=f"{server.option.label}, {where}",
            )
        )

    @staticmethod
    def _key(server_id: str, var: str) -> str:
        return f"OJARVIS_MCP_{server_id.upper().replace('-', '_')}_{var.upper()}"

    def _store_secrets(self, server_id: str, secrets: Mapping[str, str], names: list[str]) -> None:
        for name in names:
            value = _clean(secrets[name], name)
            self._backend.set(self._key(server_id, name), value)
            self._redactor.add_value(value)

    def _secret_values(self, server: InstalledServer) -> dict[str, str]:
        values = {}
        for name in server.secret_names:
            value = self._backend.get(self._key(server.id, name))
            if value:
                values[name] = value
        return values

    def _forget_secrets(self, server: InstalledServer) -> None:
        for name in server.secret_names:
            with contextlib.suppress(Exception):
                self._backend.delete(self._key(server.id, name))

    async def _remove_storage(self, server_id: str) -> None:
        """Le dossier (bubblewrap) ou le volume (Docker) où le serveur gardait son cache."""
        home = self._data_dir / "mcp" / server_id
        await anyio.to_thread.run_sync(lambda: shutil.rmtree(home, ignore_errors=True))
        docker = shutil.which("docker")
        if docker is None or self._launcher is not None:
            return
        with contextlib.suppress(Exception):
            process = await asyncio.create_subprocess_exec(
                docker,
                "volume",
                "rm",
                "-f",
                f"ojarvis-mcp-{server_id}",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(process.wait(), 15)

    async def _publish(self, event: str, server: InstalledServer) -> None:
        await self._bus.publish(
            event,
            {
                "id": server.id,
                "title": server.title,
                "version": server.version,
                "enabled": server.enabled,
            },
            source="mcp",
        )
