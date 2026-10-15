"""Une connexion à un serveur MCP (GitHub, Notion, Google Agenda…).

Chaque serveur vit dans sa propre tâche : on s'y connecte, on liste ses outils, puis la
connexion reste ouverte jusqu'à l'arrêt. Le niveau de permission de chaque outil vient de
ses annotations MCP : lecture seule → niveau 1, destructeur → niveau 3, sinon niveau 2
(prudent par défaut : un outil inconnu agit, donc il attend ta validation).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ojarvis.core.logs import get_logger
from ojarvis.tools.base import Level

log = get_logger(__name__)

CONNECT_TIMEOUT_S = 90.0
CALL_TIMEOUT_S = 60.0
MAX_RESULT_CHARS = 12_000


@dataclass(frozen=True)
class McpTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    level: Level


def tool_level(annotations: Any) -> Level:
    if annotations is None:
        return Level.AGIR
    if getattr(annotations, "destructive_hint", None) is True:
        return Level.DETRUIRE
    if getattr(annotations, "read_only_hint", None) is True:
        return Level.LIRE
    return Level.AGIR


def result_text(result: Any) -> str:
    """Le texte d'un résultat d'outil MCP (contenu textuel, sinon données structurées)."""
    parts: list[str] = []
    for item in getattr(result, "content", None) or []:
        text = getattr(item, "text", None)
        if isinstance(text, str):
            parts.append(text)
        else:
            parts.append(f"[{getattr(item, 'type', 'contenu')}]")
    if not parts and getattr(result, "structured_content", None) is not None:
        parts.append(str(result.structured_content))
    text = "\n".join(parts).strip()
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + "\n[…résultat tronqué]"
    return text


class McpCallError(RuntimeError):
    pass


@dataclass
class ConnectionState:
    status: str = "arrêté"  # arrêté | connexion | prêt | erreur
    error: str | None = None
    tools: dict[str, McpTool] = field(default_factory=dict)
    detail: str | None = None


class McpConnection:
    """`target` : ce que `mcp.Client` accepte (URL, paramètres stdio, serveur en mémoire)."""

    def __init__(self, name: str, target: Callable[[], Any], *, detail: str | None = None) -> None:
        self.name = name
        self._target = target
        self.state = ConnectionState(detail=detail)
        self._client: Any = None
        self._task: asyncio.Task[None] | None = None
        self._ready = asyncio.Event()
        self._stop = asyncio.Event()
        self._lock = asyncio.Lock()

    async def start(self, *, wait: bool = True) -> ConnectionState:
        if self._task is None or self._task.done():
            self._ready.clear()
            self._stop.clear()
            self.state.status = "connexion"
            self.state.error = None
            self._task = asyncio.create_task(self._run())
        if wait:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._ready.wait(), CONNECT_TIMEOUT_S)
            if not self._ready.is_set():
                self.state.status = "erreur"
                self.state.error = "le serveur ne répond pas"
        return self.state

    async def _run(self) -> None:
        from mcp import Client  # noqa: PLC0415

        try:
            async with Client(self._target(), read_timeout_seconds=CALL_TIMEOUT_S) as client:
                tools: dict[str, McpTool] = {}
                cursor: str | None = None
                while True:
                    page = await client.list_tools(cursor=cursor)
                    for tool in page.tools:
                        tools[tool.name] = McpTool(
                            tool.name,
                            (tool.description or tool.title or tool.name).strip()[:500],
                            dict(tool.input_schema or {"type": "object"}),
                            tool_level(tool.annotations),
                        )
                    cursor = page.next_cursor
                    if not cursor:
                        break
                self._client = client
                self.state.tools = tools
                self.state.status = "prêt"
                self._ready.set()
                log.info("mcp_connected", server=self.name, tools=len(tools))
                await self._stop.wait()
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # les groupes de tâches d'anyio lèvent des ExceptionGroup
            self.state.status = "erreur"
            self.state.error = _describe(exc)
            log.warning("mcp_connection_failed", server=self.name, error=self.state.error)
        finally:
            self._client = None
            if self.state.status == "prêt":
                self.state.status = "arrêté"
            self._ready.set()

    async def call(self, tool: str, arguments: dict[str, Any]) -> tuple[str, bool]:
        """Rend (texte, en_erreur)."""
        if self._client is None:
            await self.start()
        client = self._client
        if client is None:
            raise McpCallError(f"{self.name} indisponible : {self.state.error or 'non connecté'}")
        async with self._lock:
            try:
                result = await asyncio.wait_for(client.call_tool(tool, arguments), CALL_TIMEOUT_S)
            except TimeoutError as exc:
                raise McpCallError(f"{self.name} ne répond pas (outil {tool})") from exc
            except Exception as exc:
                raise McpCallError(f"{self.name} : {_describe(exc)}") from exc
        return result_text(result), bool(getattr(result, "is_error", False))

    async def close(self) -> None:
        self._stop.set()
        if self._task is not None:
            with contextlib.suppress(TimeoutError, asyncio.CancelledError, Exception):
                await asyncio.wait_for(asyncio.shield(self._task), 10)
            if not self._task.done():
                self._task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await self._task
        self.state.status = "arrêté"


def _describe(exc: BaseException) -> str:
    """Message court et sans secret (pas d'adresse ni d'en-tête)."""
    if isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        return _describe(exc.exceptions[0])
    message = getattr(exc, "message", None) or str(exc) or type(exc).__name__
    return f"{type(exc).__name__}: {message}"[:200]
