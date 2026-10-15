"""Outils des intégrations MCP : découvrir les outils d'un serveur, puis les appeler.

Deux outils plutôt que des dizaines : le modèle regarde d'abord ce que propose GitHub,
Notion ou ton agenda (niveau 1), puis appelle l'outil voulu. Le niveau de l'appel est
celui de l'outil MCP (lecture seule → 1, destructeur → 3, sinon 2) : créer une issue ou
un événement attend donc ta validation, comme toute action.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar, Literal

import jsonschema
from pydantic import Field

from ojarvis.core.errors import UpstreamError
from ojarvis.integrations.connection import McpCallError, McpTool
from ojarvis.integrations.manager import SERVERS, IntegrationManager
from ojarvis.llm.types import ToolSpec
from ojarvis.tools.base import (
    LEVEL_LABELS,
    InvalidToolArgumentsError,
    Level,
    Tool,
    ToolArgs,
    ToolContext,
    ToolOutput,
)

Server = Literal["github", "notion", "agenda"]
_ABOUT = ", ".join(f"{s.name} ({s.about})" for s in SERVERS.values())


def _schema_line(tool: McpTool) -> str:
    properties = tool.input_schema.get("properties", {}) or {}
    required = set(tool.input_schema.get("required", []) or [])
    args = []
    for key, value in list(properties.items())[:15]:
        kind = value.get("type", "?") if isinstance(value, dict) else "?"
        args.append(f"{key}{'*' if key in required else ''}: {kind}")
    return ", ".join(args) or "aucun"


class ServerArgs(ToolArgs):
    serveur: Server = Field(description=f"Intégration : {_ABOUT}.")


class ListIntegrationTools(Tool[ServerArgs]):
    name: ClassVar[str] = "integrations_outils"
    description: ClassVar[str] = (
        f"Liste les outils d'une intégration ({_ABOUT}) avec leurs arguments (* = obligatoire). "
        "À faire avant integration_appeler."
    )
    Args: ClassVar[type[ToolArgs]] = ServerArgs
    level: ClassVar[Level] = Level.LIRE

    def __init__(self, manager: IntegrationManager) -> None:
        self._manager = manager

    def describe(self, args: ServerArgs) -> str:
        return f"Regarder ce que propose {SERVERS[args.serveur].label}"

    async def run(self, args: ServerArgs, ctx: ToolContext) -> ToolOutput:
        del ctx
        try:
            tools = await self._manager.ensure(args.serveur)
        except McpCallError as exc:
            raise UpstreamError(str(exc)) from exc
        lines = [
            f"- {t.name} [niveau {int(t.level)}] : {t.description}\n  arguments : {_schema_line(t)}"
            for t in tools.values()
        ]
        return ToolOutput("\n".join(lines) or "Aucun outil.", {"outils": list(tools)})


class CallArgs(ToolArgs):
    serveur: Server = Field(description="Intégration : github, notion ou agenda.")
    outil: str = Field(min_length=1, max_length=100, description="Nom exact de l'outil.")
    arguments: dict[str, Any] = Field(default_factory=dict, description="Arguments de l'outil.")


class CallIntegration(Tool[CallArgs]):
    name: ClassVar[str] = "integration_appeler"
    description: ClassVar[str] = (
        "Appelle un outil d'une intégration (GitHub, Notion, Google Agenda). Lecture : "
        "niveau 1 ; créer ou modifier : niveau 2 ; supprimer : niveau 3."
    )
    Args: ClassVar[type[ToolArgs]] = CallArgs
    level: ClassVar[Level] = Level.AGIR

    def __init__(self, manager: IntegrationManager) -> None:
        self._manager = manager

    def spec(self) -> ToolSpec:
        # Le niveau dépend de l'outil appelé : pas de niveau unique dans la description.
        schema = self.Args.model_json_schema()
        schema.pop("title", None)
        return ToolSpec(self.name, self.description, schema)

    def parse(self, raw: dict[str, Any]) -> CallArgs:
        args: CallArgs = super().parse(raw)
        tool = self._manager.known_tool(args.serveur, args.outil)
        if tool is not None:
            try:
                jsonschema.validate(args.arguments, tool.input_schema)
            except jsonschema.ValidationError as exc:
                where = ".".join(str(p) for p in exc.absolute_path) or "arguments"
                raise InvalidToolArgumentsError(
                    f"Arguments invalides pour {args.outil} ({where} : {exc.message})."
                ) from exc
            except jsonschema.SchemaError:
                pass  # schéma du serveur illisible : le serveur validera lui-même
        return args

    def level_for(self, args: CallArgs) -> Level:
        tool = self._manager.known_tool(args.serveur, args.outil)
        # Outil pas encore connu (serveur pas démarré) : prudence, c'est une action.
        return tool.level if tool is not None else Level.AGIR

    def describe(self, args: CallArgs) -> str:
        label = SERVERS[args.serveur].label
        shown = json.dumps(args.arguments, ensure_ascii=False)
        shown = shown if len(shown) <= 160 else shown[:157] + "…"
        level = self.level_for(args)
        return f"{label} : {args.outil} {shown} ({LEVEL_LABELS[level]})"

    async def run(self, args: CallArgs, ctx: ToolContext) -> ToolOutput:
        del ctx
        try:
            text, is_error = await self._manager.call(args.serveur, args.outil, args.arguments)
        except McpCallError as exc:
            raise UpstreamError(str(exc)) from exc
        if is_error:
            raise UpstreamError(f"{SERVERS[args.serveur].label} : {text[:300]}")
        return ToolOutput(
            text or "(rien)",
            {"serveur": args.serveur, "outil": args.outil},
            external=True,
            source=f"{SERVERS[args.serveur].label} ({args.outil})",
        )


def integration_tools(manager: IntegrationManager) -> list[Tool[Any]]:
    return [ListIntegrationTools(manager), CallIntegration(manager)]
