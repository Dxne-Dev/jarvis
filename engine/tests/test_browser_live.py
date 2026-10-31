"""Voir Jarvis agir (#34) : la page filmée pour l'app, et Chromium en fenêtre sur demande."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ojarvis.browser.live import LiveFrame, LiveView
from ojarvis.browser.session import BrowserSession
from ojarvis.browser.vault import CookieVault
from ojarvis.services import Services
from tests.test_browser_pages import site  # noqa: F401 - la boutique de test, servie en local


class FakeCdp:
    def __init__(self, *, broken: bool = False) -> None:
        self.sent: list[str] = []
        self._handlers: dict[str, Callable[[dict[str, Any]], None]] = {}
        self._broken = broken

    def on(self, event: str, handler: Callable[[dict[str, Any]], None]) -> None:
        self._handlers[event] = handler

    async def send(self, method: str, params: dict[str, Any] | None = None) -> None:
        del params
        if self._broken:
            raise RuntimeError("protocole indisponible")
        self.sent.append(method)

    async def detach(self) -> None:
        self.sent.append("detach")

    def paint(self, number: int) -> None:
        data = base64.b64encode(b"\xff\xd8image" + bytes([number])).decode()
        self._handlers["Page.screencastFrame"]({"data": data, "sessionId": number})


class FakePage:
    def __init__(self, url: str, cdp: FakeCdp) -> None:
        self.url = url
        self.cdp = cdp
        self.context = self

    async def new_cdp_session(self, page: FakePage) -> FakeCdp:
        assert page is self
        return self.cdp


def shown(live: LiveView) -> LiveFrame | None:
    return live.frame


async def settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0.02)


async def test_only_the_last_image_is_kept_and_the_app_is_told_without_flooding() -> None:
    told: list[tuple[int, str]] = []

    async def notify(seq: int, url: str) -> None:
        told.append((seq, url))

    live = LiveView(notify, notify_every_s=0.05)
    page = FakePage("https://boutique.example/", FakeCdp())
    await live.follow(page)
    assert page.cdp.sent == ["Page.startScreencast"]
    for number in range(5):  # cinq images d'affilée
        page.cdp.paint(number)
    await settle()
    assert live.frame == LiveFrame(5, b"\xff\xd8image\x04", "https://boutique.example/")
    assert page.cdp.sent.count("Page.screencastFrameAck") == 5  # Chromium peut continuer
    assert 1 <= len(told) < 5
    assert told[-1] == (5, "https://boutique.example/")  # la dernière n'est jamais oubliée
    await live.close()


async def test_a_new_page_is_filmed_instead_and_the_old_one_is_ignored() -> None:
    live = LiveView(notify_every_s=0.0)
    first = FakePage("https://a.example/", FakeCdp())
    second = FakePage("https://b.example/", FakeCdp())
    await live.follow(first)
    await live.follow(second)
    assert first.cdp.sent[-2:] == ["Page.stopScreencast", "detach"]
    first.cdp.paint(1)
    await settle()
    assert shown(live) is None  # une image de la page d'avant
    second.cdp.paint(2)
    await settle()
    frame = shown(live)
    assert frame is not None
    assert frame.url == "https://b.example/"
    await live.close()


async def test_filming_stops_when_jarvis_leaves_the_browser_alone() -> None:
    live = LiveView(linger_s=0.05)
    page = FakePage("https://a.example/", FakeCdp())
    await live.follow(page)
    await asyncio.sleep(0.15)
    assert page.cdp.sent[-2:] == ["Page.stopScreencast", "detach"]
    await live.close()


async def test_a_broken_live_view_never_stops_the_browser() -> None:
    live = LiveView()
    await live.follow(FakePage("https://a.example/", FakeCdp(broken=True)))  # pas d'exception
    assert live.frame is None
    await live.close()


def test_the_app_reads_the_last_image_on_this_machine(
    client: TestClient, services: Services
) -> None:
    assert client.get("/v1/browser/live").status_code == 404
    live = services.browser.session.live
    assert live is not None
    live.frame = LiveFrame(7, b"\xff\xd8jpeg", "https://boutique.example/")
    response = client.get("/v1/browser/live")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["x-frame-seq"] == "7"
    assert response.content == b"\xff\xd8jpeg"


class FakeContext:
    def set_default_timeout(self, _ms: int) -> None:
        return None

    def on(self, _event: str, _handler: Any) -> None:
        return None

    async def close(self) -> None:
        return None


class FakeBrowser:
    def __init__(self, headless: bool) -> None:
        self.headless = headless
        self.connected = True

    def is_connected(self) -> bool:
        return self.connected

    async def new_context(self, **_options: Any) -> FakeContext:
        return FakeContext()

    async def close(self) -> None:
        self.connected = False


async def test_the_show_option_reopens_chromium_in_a_window(tmp_path: Path) -> None:
    visible = {"value": False}
    session = BrowserSession(
        CookieVault(tmp_path / "c.bin", lambda: "k"), visible=lambda: visible["value"]
    )
    launched: list[FakeBrowser] = []

    async def launch(*, headless: bool) -> FakeBrowser:
        launched.append(FakeBrowser(headless))
        return launched[-1]

    session._launch = launch  # type: ignore[method-assign]
    await session._context(False)
    await session._context(False)
    assert [b.headless for b in launched] == [True]  # un seul lancement, en arrière-plan
    visible["value"] = True
    await session._context(False)
    assert [b.headless for b in launched] == [True, False]
    assert not launched[0].connected  # l'ancien Chromium est fermé
    launched[1].connected = False  # tu fermes la fenêtre toi-même
    await session._context(False)
    assert [b.headless for b in launched] == [True, False, False]
    await session.close()


async def test_a_real_page_is_filmed_while_jarvis_clicks(tmp_path: Path, site: int) -> None:  # noqa: F811
    told: list[int] = []

    async def notify(seq: int, _url: str) -> None:
        told.append(seq)

    session = BrowserSession(
        CookieVault(tmp_path / "c.bin", lambda: "k"),
        allowed_hosts=("127.0.0.1",),
        live=LiveView(notify, notify_every_s=0.05),
    )
    try:
        await session._context(False)
    except Exception as exc:  # Chromium de Playwright absent sur cette machine
        await session.close()
        pytest.skip(f"Chromium indisponible : {exc}")
    try:
        await session.goto(f"http://127.0.0.1:{site}/")
        await session.fill("Recherche", "thé vert")
        await session.click("Chercher")
        await asyncio.sleep(0.5)
        assert session.live is not None
        frame = session.live.frame
        assert frame is not None
        assert frame.jpeg.startswith(b"\xff\xd8")  # une image JPEG
        assert "/cherche" in frame.url
        assert told
    finally:
        await session.close()
