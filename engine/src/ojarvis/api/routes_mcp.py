"""Serveurs MCP du registre : chercher, essayer, installer, désactiver, retirer.

Installer est une extension (niveau 3) : double confirmation, journal. L'essai lance le
serveur isolé et montre ses outils avec leur niveau, avant toute décision. Les clés saisies
vont au trousseau et ne reviennent jamais à l'interface.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from ojarvis.agent.executor import DoubleConfirmationRequiredError
from ojarvis.api.deps import ServicesDep
from ojarvis.core.errors import UnavailableError
from ojarvis.integrations.mcp_registry import InstalledServer
from ojarvis.integrations.registry import RegistryEntry, RegistryError, Runtimes
from ojarvis.services import Services

router = APIRouter(prefix="/v1/mcp")


class SettingOut(BaseModel):
    name: str
    description: str
    required: bool
    secret: bool
    default: str | None


class OptionOut(BaseModel):
    kind: str
    label: str
    where: str
    settings: list[SettingOut]


class RegistryEntryOut(BaseModel):
    name: str
    title: str
    description: str
    version: str
    repository: str | None
    website: str | None
    option: OptionOut | None
    why_not: str | None
    installed_id: str | None


class ProbeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=3, max_length=200)
    version: str = Field(min_length=1, max_length=64)
    variables: dict[str, str] = Field(default_factory=dict)
    secrets: dict[str, str] = Field(default_factory=dict)


class InstallIn(ProbeIn):
    double_confirm: bool = False


class ProbeOut(BaseModel):
    ok: bool
    tools: list[dict[str, Any]]
    error: str | None
    runner: str
    seconds: float


class InstalledOut(BaseModel):
    id: str
    registry_name: str
    title: str
    description: str
    version: str
    kind: str
    label: str
    where: str
    enabled: bool
    status: str
    error: str | None
    tools: list[dict[str, Any]]
    variables: dict[str, str]
    secret_names: list[str]
    installed_at: datetime


class EnabledIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


def _entry(entry: RegistryEntry, runtimes: Runtimes, services: Services) -> RegistryEntryOut:
    option = entry.best(runtimes)
    installed = [s.id for s in services.mcp.installed() if s.registry_name == entry.name]
    return RegistryEntryOut(
        name=entry.name,
        title=entry.title,
        description=entry.description,
        version=entry.version,
        repository=entry.repository,
        website=entry.website,
        option=OptionOut(
            kind=option.kind,
            label=option.label,
            where=option.where,
            settings=[
                SettingOut(
                    name=v.name,
                    description=v.description,
                    required=v.required,
                    secret=v.secret,
                    default=v.default,
                )
                for v in option.asked()
            ],
        )
        if option
        else None,
        why_not=None if option else entry.why_not(runtimes),
        installed_id=installed[0] if installed else None,
    )


def _installed(server: InstalledServer, services: Services) -> InstalledOut:
    status = services.mcp.status(server.id)
    live = status["tools"]
    return InstalledOut(
        id=server.id,
        registry_name=server.registry_name,
        title=server.title,
        description=server.description,
        version=server.version,
        kind=server.option.kind,
        label=server.option.label,
        where=server.option.where,
        enabled=server.enabled,
        status=status["status"] if server.enabled else "désactivé",
        error=status["error"],
        tools=live or server.tools,
        variables=server.variables,
        secret_names=server.secret_names,
        installed_at=server.installed_at,
    )


async def _journal(
    services: Services, action: str, level: int, summary: str, **details: Any
) -> None:
    await services.journal.append(
        actor="utilisateur", action=action, level=level, summary=summary, details=details
    )


@router.get("/registry")
async def search_registry(
    services: ServicesDep, q: Annotated[str, Query(min_length=2, max_length=100)]
) -> list[RegistryEntryOut]:
    try:
        entries = await services.mcp.search(q)
    except RegistryError as exc:
        raise UnavailableError(str(exc).capitalize() + ".") from exc
    runtimes = await services.mcp.runtimes()
    return [_entry(e, runtimes, services) for e in entries]


@router.post("/probe")
async def probe_server(body: ProbeIn, services: ServicesDep) -> ProbeOut:
    result = await services.mcp.probe(body.name, body.version, body.variables, body.secrets)
    return ProbeOut(
        ok=result.ok,
        tools=result.tools,
        error=result.error,
        runner=result.runner,
        seconds=result.seconds,
    )


@router.get("/servers")
async def list_servers(services: ServicesDep) -> list[InstalledOut]:
    return [_installed(s, services) for s in services.mcp.installed()]


@router.post("/servers", status_code=201)
async def install_server(body: InstallIn, services: ServicesDep) -> InstalledOut:
    if not body.double_confirm:
        raise DoubleConfirmationRequiredError(
            "Installer un serveur MCP lui donne de nouveaux outils : confirme une seconde fois."
        )
    server = await services.mcp.install(body.name, body.version, body.variables, body.secrets)
    await _journal(
        services,
        "mcp.installe",
        3,
        f"Serveur MCP installé : {server.label}",
        serveur=server.id,
        registre=server.registry_name,
        lancement=server.option.label,
        outils=len(server.tools),
    )
    return _installed(server, services)


@router.patch("/servers/{server_id}")
async def toggle_server(server_id: str, body: EnabledIn, services: ServicesDep) -> InstalledOut:
    server = await services.mcp.set_enabled(server_id, body.enabled)
    verb = "réactivé" if body.enabled else "désactivé"
    await _journal(
        services, "mcp.etat", 2, f"Serveur MCP {verb} : {server.label}", serveur=server.id
    )
    return _installed(server, services)


@router.delete("/servers/{server_id}", status_code=204)
async def uninstall_server(
    server_id: str, services: ServicesDep, double_confirm: bool = False
) -> Response:
    if not double_confirm:
        raise DoubleConfirmationRequiredError("Retirer un serveur MCP : confirme une seconde fois.")
    server = await services.mcp.uninstall(server_id)
    await _journal(
        services, "mcp.retire", 3, f"Serveur MCP retiré : {server.label}", serveur=server.id
    )
    return Response(status_code=204)
