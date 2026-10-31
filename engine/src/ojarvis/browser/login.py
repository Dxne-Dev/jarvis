"""Se connecter soi-même à un site, dans une fenêtre visible de Chromium : Jarvis ne tape
jamais un mot de passe ; il garde la session obtenue (filtrée par domaine). Et le
téléchargement de Chromium au premier usage.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import Any

from ojarvis.browser.vault import State
from ojarvis.core.logs import get_logger

log = get_logger(__name__)

LOGIN_SNAPSHOT_S = 2.0

_install_lock = asyncio.Lock()


async def install_chromium(timeout_s: float = 900.0) -> bool:
    """Télécharge le Chromium de Playwright (dans ~/.cache/ms-playwright) avec son pilote."""
    from playwright._impl._driver import (  # noqa: PLC0415
        compute_driver_executable,
        get_driver_env,
    )

    async with _install_lock:
        node, cli = compute_driver_executable()
        log.info("chromium_installing")
        try:
            process = await asyncio.create_subprocess_exec(
                node,
                cli,
                "install",
                "chromium",
                env=get_driver_env(),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            ok = await asyncio.wait_for(process.wait(), timeout_s) == 0
        except (OSError, TimeoutError):
            ok = False
        log.info("chromium_installed" if ok else "chromium_install_failed")
        return ok


class _LoginWindow:
    """Fenêtre de connexion : son état est relevé toutes les 2 s, et une dernière fois
    quand tu la fermes."""

    def __init__(
        self, browser: Any, context: Any, on_closed: Callable[[], Awaitable[Any]] | None
    ) -> None:
        self.browser = browser
        self.context = context
        self.state: State = {"cookies": [], "origins": []}
        self.done = asyncio.Event()
        self._on_closed = on_closed
        self._closing = False
        self._watch_task: asyncio.Task[None] | None = None
        self._final_task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._watch_task = asyncio.create_task(self._watch())

    def closed(self) -> None:
        """Page ou navigateur fermé par toi : dernier relevé, puis fin de la connexion."""
        if self._closing:
            return
        self._closing = True
        self._final_task = asyncio.create_task(self._finalize())

    async def _finalize(self) -> None:
        with contextlib.suppress(Exception):
            self.state = await self.context.storage_state()
        self.done.set()
        if self._on_closed is not None:
            await self._on_closed()

    async def snapshot(self) -> None:
        if self._closing:
            return
        with contextlib.suppress(Exception):
            self.state = await self.context.storage_state()

    async def _watch(self) -> None:
        while not self.done.is_set():
            await self.snapshot()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.done.wait(), LOGIN_SNAPSHOT_S)

    async def close(self) -> None:
        self._closing = True
        self.done.set()
        if self._watch_task is not None:
            self._watch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._watch_task
        with contextlib.suppress(Exception):
            await self.context.close()
        with contextlib.suppress(Exception):
            await self.browser.close()
