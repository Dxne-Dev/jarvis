"""Outils du registre MCP : chercher un serveur (lecture), l'installer (niveau 3).

Installer passe toujours par un plan à double confirmation ; le serveur est essayé isolé
avant d'être ajouté. Une clé n'est jamais transmise par le modèle : si le serveur en demande
une, tu l'installes depuis Skills et plugins, où tu la saisis toi-même.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, ClassVar

from pydantic import Field

from ojarvis.core.errors import InvalidInputError
from ojarvis.integrations.mcp_registry import McpRegistryService
from ojarvis.integrations.registry import RegistryEntry
from ojarvis.tools.base import Level, Tool, ToolArgs, ToolContext, ToolOutput

LEVEL_WORDS = {1: "lecture", 2: "action", 3: "destruction"}


def _settings(entry: RegistryEntry, service: McpRegistryService) -> str:
    runtimes = service.last_runtimes
    option = entry.best(runtimes) if runtimes else None
    if option is None:
        return f"impossible ici : {entry.why_not(runtimes) if runtimes else 'inconnu'}"
    asked = option.asked()
    names = [f"{v.name}{' (clé)' if v.secret else ''}{'*' if v.required else ''}" for v in asked]
    text = f"{option.label}, {option.where}"
    return f"{text} ; réglages : {', '.join(names)}" if names else text


class SearchArgs(ToolArgs):
    requete: str = Field(
        min_length=2,
        max_length=100,
        description="Mot du nom du serveur (ex. wikipedia, sqlite, github).",
    )


class SearchRegistry(Tool[SearchArgs]):
    name: ClassVar[str] = "mcp_chercher"
    description: ClassVar[str] = (
        "Cherche des serveurs MCP dans le registre officiel : ce qu'ils font, leur version, "
        "où ils tourneraient et les réglages demandés (* = obligatoire)."
    )
    Args: ClassVar[type[ToolArgs]] = SearchArgs
    level: ClassVar[Level] = Level.LIRE

    def __init__(self, service: McpRegistryService) -> None:
        self._service = service

    def describe(self, args: SearchArgs) -> str:
        return f"Chercher « {args.requete} » dans le registre MCP"

    async def run(self, args: SearchArgs, ctx: ToolContext) -> ToolOutput:
        del ctx
        entries = await self._service.search(args.requete)
        await self._service.runtimes()
        lines = [
            f"- {e.name} v{e.version} — {e.title} : {e.description[:200]}\n"
            f"  {_settings(e, self._service)}"
            for e in entries[:8]
        ]
        return ToolOutput(
            "\n".join(lines) or "Aucun serveur ne correspond.",
            {"serveurs": [{"nom": e.name, "version": e.version} for e in entries[:8]]},
            external=True,
            source="registre MCP",
        )


class InstallArgs(ToolArgs):
    nom: str = Field(
        min_length=3,
        max_length=200,
        pattern=r"^[A-Za-z0-9.-]+/[A-Za-z0-9._-]+$",
        description="Nom exact dans le registre (ex. io.github.cyanheads/wikipedia-mcp-server).",
    )
    version: str = Field(max_length=64, pattern=r"^[0-9][A-Za-z0-9.+-]*$")
    reglages: dict[str, str] = Field(
        default_factory=dict,
        description="Réglages ordinaires demandés par le serveur (jamais une clé).",
    )


class InstallServer(Tool[InstallArgs]):
    name: ClassVar[str] = "mcp_installer"
    description: ClassVar[str] = (
        "Installe un serveur MCP du registre : il est essayé isolé, puis ses outils sont "
        "utilisables avec integrations_outils et integration_appeler. Double confirmation."
    )
    Args: ClassVar[type[ToolArgs]] = InstallArgs
    level: ClassVar[Level] = Level.DETRUIRE

    def __init__(self, service: McpRegistryService) -> None:
        self._service = service

    def describe(self, args: InstallArgs) -> str:
        entry = self._service.cached(args.nom, args.version)
        if entry is None:
            return f"Installer le serveur MCP « {args.nom} » v{args.version} (essayé isolé d'abord)"
        return (
            f"Installer le serveur MCP « {entry.title} » ({entry.name}) v{entry.version} : "
            f"{_settings(entry, self._service)} ; essayé isolé d'abord ; chaque outil gardera "
            "son niveau (lecture, action ou destruction)"
        )

    async def run(self, args: InstallArgs, ctx: ToolContext) -> ToolOutput:
        del ctx
        _, option, _ = await self._service.plan(args.nom, args.version)
        keys = [v.name for v in option.asked() if v.secret and v.required]
        if keys:
            raise InvalidInputError(
                f"Ce serveur demande une clé ({', '.join(keys)}) : l'utilisateur l'installe "
                "depuis Skills et plugins, où il la saisit lui-même."
            )
        server = await self._service.install(args.nom, args.version, args.reglages, {})
        levels = Counter(LEVEL_WORDS.get(int(t["level"]), "?") for t in server.tools)
        counts = ", ".join(f"{n} en {w}" for w, n in levels.items())
        return ToolOutput(
            f"Serveur {server.label} installé ({len(server.tools)} outils : {counts}). "
            f'Ses outils : integrations_outils(serveur="{server.id}").',
            {"serveur": server.id},
        )


def mcp_tools(service: McpRegistryService) -> list[Tool[Any]]:
    return [SearchRegistry(service), InstallServer(service)]
