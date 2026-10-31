"""La page de Jarvis en direct (#34) : ce que montre son Chromium, pendant qu'il agit.

Chromium envoie une image à chaque changement de la page (protocole de débogage,
« screencast »). Seule la dernière est gardée ; l'app la lit sur 127.0.0.1, rien ne part
ailleurs. Un petit événement, quatre fois par seconde au plus, la prévient qu'une nouvelle
image l'attend. Le film s'arrête quand Jarvis ne touche plus au navigateur.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from ojarvis.core.logs import get_logger

log = get_logger(__name__)

#: Après la dernière action, la page reste filmée ce temps-là (on voit le résultat).
LINGER_S = 20.0
NOTIFY_EVERY_S = 0.25
SCREENCAST = {"format": "jpeg", "quality": 60, "maxWidth": 1024, "maxHeight": 768}

Notify = Callable[[int, str], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class LiveFrame:
    seq: int
    jpeg: bytes
    url: str


class LiveView:
    def __init__(
        self,
        notify: Notify | None = None,
        *,
        linger_s: float = LINGER_S,
        notify_every_s: float = NOTIFY_EVERY_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.frame: LiveFrame | None = None
        self._notify = notify
        self._linger_s = linger_s
        self._every_s = notify_every_s
        self._clock = clock
        self._page: Any = None
        self._cdp: Any = None
        self._seq = 0
        self._last_notice = float("-inf")
        self._notice: asyncio.Task[None] | None = None
        self._idle: asyncio.TimerHandle | None = None
        self._tasks: set[asyncio.Task[Any]] = set()

    def _spawn(self, coroutine: Awaitable[Any]) -> None:
        task = asyncio.ensure_future(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def follow(self, page: Any) -> None:
        """Filme cette page (la précédente ne l'est plus), jusqu'à `linger_s` après l'appel."""
        self._keep_alive()
        if page is self._page and self._cdp is not None:
            return
        await self.stop()
        self._page = page
        try:
            cdp = await page.context.new_cdp_session(page)
            cdp.on("Page.screencastFrame", lambda params: self._spawn(self._frame(cdp, params)))
            await cdp.send("Page.startScreencast", SCREENCAST)
            self._cdp = cdp
        except Exception as exc:
            # La vue en direct ne doit jamais empêcher Jarvis d'utiliser son navigateur.
            log.warning("live_view_unavailable", error=type(exc).__name__)

    def _keep_alive(self) -> None:
        if self._idle is not None:
            self._idle.cancel()
        loop = asyncio.get_running_loop()
        self._idle = loop.call_later(self._linger_s, lambda: self._spawn(self.stop()))

    async def _frame(self, cdp: Any, params: dict[str, Any]) -> None:
        with contextlib.suppress(Exception):
            await cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})
        if cdp is not self._cdp:
            return  # une image de la page d'avant
        self._seq += 1
        url = str(getattr(self._page, "url", "") or "")
        self.frame = LiveFrame(self._seq, base64.b64decode(params["data"]), url)
        if self._notice is None:
            self._notice = asyncio.ensure_future(self._announce())

    async def _announce(self) -> None:
        """Prévient l'app, au plus tous les `notify_every_s` ; la dernière image n'est jamais
        oubliée (elle part à la fin de l'attente)."""
        try:
            wait = self._last_notice + self._every_s - self._clock()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_notice = self._clock()
            frame = self.frame
            if frame is not None and self._notify is not None:
                await self._notify(frame.seq, frame.url)
        finally:
            self._notice = None

    async def stop(self) -> None:
        cdp, self._cdp = self._cdp, None
        self._page = None
        if cdp is None:
            return
        with contextlib.suppress(Exception):
            await cdp.send("Page.stopScreencast")
        with contextlib.suppress(Exception):
            await cdp.detach()

    async def close(self) -> None:
        if self._idle is not None:
            self._idle.cancel()
            self._idle = None
        await self.stop()
        for task in list(self._tasks):
            task.cancel()
