"""Les intégrations de Jarvis, par MCP : GitHub, Notion, Google Agenda.

Serveurs officiels, versions épinglées :
- GitHub : `github/github-mcp-server` (image Docker), jeton `GITHUB_TOKEN` ;
- Notion : `@notionhq/notion-mcp-server` (npm), jeton `NOTION_TOKEN`, lancé dans un
  conteneur Node (sans accès à tes fichiers) quand Docker est là ;
- Google Agenda : voir `google.py` (serveur officiel de Google, sinon celui de Jarvis).

Les jetons passent par l'environnement du seul processus du serveur, jamais par sa ligne
de commande. Chaque serveur démarre en arrière-plan ; s'il tombe, l'intégration est
signalée indisponible et le reste de Jarvis continue.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ojarvis.core.logs import get_logger
from ojarvis.integrations.connection import McpCallError, McpConnection, McpTool
from ojarvis.sandbox.runner import docker_available

log = get_logger(__name__)

GITHUB_IMAGE = "ghcr.io/github/github-mcp-server:v1.12.2"
GITHUB_TOOLSETS = "context,repos,issues,pull_requests,notifications"
NOTION_PACKAGE = "@notionhq/notion-mcp-server@2.5.2"
NODE_IMAGE = "node:24.21.0-alpine3.24"


@dataclass(frozen=True)
class ServerSpec:
    name: str
    label: str
    #: À quoi il sert (montré au modèle et dans Réglages).
    about: str
    secret: str


SERVERS: dict[str, ServerSpec] = {
    "github": ServerSpec(
        "github",
        "GitHub",
        "dépôts, issues, pull requests, notifications",
        "GITHUB_TOKEN",
    ),
    "notion": ServerSpec("notion", "Notion", "pages et bases de données", "NOTION_TOKEN"),
    "agenda": ServerSpec("agenda", "Google Agenda", "événements de ton agenda", "GOOGLE_CLIENT_ID"),
}


def _base_env() -> dict[str, str]:
    return {k: os.environ[k] for k in ("PATH", "HOME", "LANG") if k in os.environ}


def github_target(token: str, *, docker: str) -> Any:
    from mcp import StdioServerParameters  # noqa: PLC0415

    return StdioServerParameters(
        command=docker,
        args=[
            "run",
            "-i",
            "--rm",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--memory",
            "256m",
            "-e",
            "GITHUB_PERSONAL_ACCESS_TOKEN",
            "-e",
            "GITHUB_TOOLSETS",
            GITHUB_IMAGE,
        ],
        env={
            **_base_env(),
            "GITHUB_PERSONAL_ACCESS_TOKEN": token,
            "GITHUB_TOOLSETS": GITHUB_TOOLSETS,
        },
    )


def notion_target(token: str, *, docker: str | None) -> Any:
    from mcp import StdioServerParameters  # noqa: PLC0415

    env = {**_base_env(), "NOTION_TOKEN": token}
    if docker is not None:
        return StdioServerParameters(
            command=docker,
            args=[
                "run",
                "-i",
                "--rm",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--memory",
                "512m",
                "--user",
                "node",
                # Dossier de l'utilisateur « node » gardé d'un lancement à l'autre (cache npm :
                # démarrage rapide après le premier). Un volume neuf monté sur un dossier
                # existant de l'image en reprend les droits ; monté sur .npm, il serait à root.
                "-v",
                "ojarvis-node-home:/home/node",
                "-e",
                "npm_config_update_notifier=false",
                "-e",
                "NOTION_TOKEN",
                NODE_IMAGE,
                "npx",
                "-y",
                NOTION_PACKAGE,
            ],
            env=env,
        )
    npx = shutil.which("npx")
    if npx is None:
        raise RuntimeError("ni Docker ni Node.js : le serveur Notion ne peut pas démarrer")
    return StdioServerParameters(command=npx, args=["-y", NOTION_PACKAGE], env=env)


class IntegrationManager:
    def __init__(
        self,
        secret: Callable[[str], str | None],
        *,
        targets: dict[str, Callable[[], Any]] | None = None,
        docker: bool | None = None,
    ) -> None:
        self._secret = secret
        self._docker = docker
        self._connections: dict[str, McpConnection] = {}
        #: Cibles imposées (tests, serveur Google) : nom → fonction qui rend la cible.
        self._targets = dict(targets or {})
        self._details: dict[str, str] = {}

    def set_target(self, name: str, target: Callable[[], Any] | None, *, detail: str = "") -> None:
        """Change la façon de joindre un serveur (ex. Google : officiel ou celui de Jarvis)."""
        if target is None:
            self._targets.pop(name, None)
        else:
            self._targets[name] = target
        self._details[name] = detail
        connection = self._connections.pop(name, None)
        if connection is not None:
            asyncio.get_running_loop().create_task(connection.close())

    def configured(self, name: str) -> bool:
        if name in self._targets:
            return True
        spec = SERVERS[name]
        return name != "agenda" and bool(self._secret(spec.secret))

    async def _docker_path(self) -> str | None:
        if self._docker is None:
            self._docker = await docker_available()
        return shutil.which("docker") if self._docker else None

    async def _target(self, name: str) -> Callable[[], Any]:
        if name in self._targets:
            return self._targets[name]
        spec = SERVERS[name]
        token = self._secret(spec.secret) or ""
        docker = await self._docker_path()
        if name == "github":
            if docker is None:
                raise McpCallError("GitHub : Docker est nécessaire pour lancer son serveur MCP.")
            return lambda: github_target(token, docker=docker)
        if name == "notion":
            return lambda: notion_target(token, docker=docker)
        raise McpCallError(f"{spec.label} n'est pas encore connecté (Réglages → Intégrations).")

    async def connection(self, name: str) -> McpConnection:
        if name not in SERVERS:
            raise McpCallError(f"Intégration inconnue : {name}.")
        if not self.configured(name):
            label = SERVERS[name].label
            raise McpCallError(f"{label} n'est pas configuré (Réglages → Intégrations).")
        connection = self._connections.get(name)
        if connection is None:
            connection = McpConnection(
                name, await self._target(name), detail=self._details.get(name)
            )
            self._connections[name] = connection
        return connection

    async def ensure(self, name: str) -> dict[str, McpTool]:
        connection = await self.connection(name)
        if connection.state.status != "prêt":
            await connection.start()
        if connection.state.status != "prêt":
            raise McpCallError(f"{SERVERS[name].label} indisponible : {connection.state.error}")
        return connection.state.tools

    def known_tool(self, name: str, tool: str) -> McpTool | None:
        connection = self._connections.get(name)
        return connection.state.tools.get(tool) if connection else None

    async def call(self, name: str, tool: str, arguments: dict[str, Any]) -> tuple[str, bool]:
        tools = await self.ensure(name)
        if tool not in tools:
            raise McpCallError(f"{SERVERS[name].label} n'a pas d'outil « {tool} ».")
        connection = await self.connection(name)
        return await connection.call(tool, arguments)

    async def start_configured(self) -> None:
        """Au démarrage, sans bloquer : connexion des intégrations configurées."""
        for name in SERVERS:
            if not self.configured(name):
                continue
            try:
                connection = await self.connection(name)
                await connection.start(wait=False)
            except McpCallError as exc:
                log.info("integration_skipped", server=name, reason=str(exc))

    async def reset(self, name: str) -> None:
        connection = self._connections.pop(name, None)
        if connection is not None:
            await connection.close()

    def status(self) -> list[dict[str, Any]]:
        out = []
        for name, spec in SERVERS.items():
            connection = self._connections.get(name)
            state = connection.state if connection else None
            out.append(
                {
                    "name": name,
                    "label": spec.label,
                    "about": spec.about,
                    "configured": self.configured(name),
                    "status": state.status if state else "arrêté",
                    "error": state.error if state else None,
                    "tools": len(state.tools) if state else 0,
                    "detail": self._details.get(name) or None,
                }
            )
        return out

    async def close(self) -> None:
        for connection in list(self._connections.values()):
            await connection.close()
        self._connections.clear()
