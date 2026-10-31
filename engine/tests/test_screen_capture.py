"""La capture de l'écran (X11 ou portail) et sa lecture par un modèle de vision."""

from __future__ import annotations

import base64
import contextlib
import io
import shutil
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from jeepney import HeaderFields
from PIL import Image

from ojarvis.core.errors import UnavailableError
from ojarvis.desktop import screen
from ojarvis.desktop.screen import capture, shrink
from ojarvis.llm.errors import RateLimitedError
from ojarvis.llm.providers.fake import FakeProvider, FakeReply
from ojarvis.llm.types import LLMRequest
from ojarvis.services import Services
from ojarvis.tools.screen import LookAtScreen


def test_shrink_keeps_proportions_and_makes_a_jpeg() -> None:
    image = Image.new("RGB", (1920, 1080), (10, 20, 30))
    raw = io.BytesIO()
    image.save(raw, "PNG")
    small = shrink(raw.getvalue(), max_side=768)
    with Image.open(io.BytesIO(small)) as out:
        assert out.format == "JPEG"
        assert out.size == (768, 432)


@pytest.fixture
def xvfb() -> Iterator[str]:
    binary = shutil.which("Xvfb")
    if binary is None:
        pytest.skip("Xvfb absent")
    display = ":97"
    command = [binary, display, "-screen", "0", "800x600x24"]
    server = subprocess.Popen(command, stderr=subprocess.DEVNULL)  # noqa: S603 - Xvfb du système
    time.sleep(0.8)
    try:
        if server.poll() is not None:
            pytest.skip("Xvfb ne démarre pas")
        yield display
    finally:
        server.terminate()
        server.wait(timeout=5)


async def test_the_x11_path_captures_the_screen(xvfb: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.setenv("DISPLAY", xvfb)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    png = await capture()
    with Image.open(io.BytesIO(png)) as image:
        assert image.size == (800, 600)


class FakeBus:
    """Le bus de session vu par le portail : la question, puis la réponse par un signal."""

    unique_name = ":1.42"

    def __init__(self, code: int, uri: str) -> None:
        self.code, self.uri = code, uri
        self.sent: list[Any] = []

    def __enter__(self) -> FakeBus:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def send_and_get_reply(self, message: Any, timeout: float | None = None) -> None:
        del timeout
        self.sent.append(message)

    def filter(self, rule: Any) -> Any:
        self.rule = rule
        return contextlib.nullcontext("réponses")

    def recv_until_filtered(self, responses: Any, timeout: float) -> Any:
        del responses, timeout
        return SimpleNamespace(body=(self.code, {"uri": ("s", self.uri)}))


def test_the_portal_capture_is_read_then_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shot = tmp_path / "Capture d'écran.png"
    shot.write_bytes(b"png")
    bus = FakeBus(0, shot.as_uri())
    monkeypatch.setattr("jeepney.io.blocking.open_dbus_connection", lambda **_: bus)
    assert screen._capture_portal() == b"png"
    assert not shot.exists()  # le portail l'a écrite sur le disque : Jarvis ne la garde pas
    call = bus.sent[-1]
    assert call.header.fields[HeaderFields.member] == "Screenshot"
    _, options = call.body
    assert options["interactive"] == ("b", False)
    token = options["handle_token"][1]
    # La réponse est attendue sur le chemin que le portail dérive de notre nom et du jeton.
    path = f"/org/freedesktop/portal/desktop/request/1_42/{token}"
    assert f"path='{path}'" in bus.rule.serialise()


def test_a_refused_portal_capture_is_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = FakeBus(1, "")
    monkeypatch.setattr("jeepney.io.blocking.open_dbus_connection", lambda **_: bus)
    # Le refus vient de GNOME, pas d'un réglage de Jarvis : le message le dit, et où le changer.
    with pytest.raises(UnavailableError, match="refusée par le bureau") as refused:
        screen._capture_portal()
    assert "pas par Jarvis" in refused.value.message


async def test_capture_follows_the_session(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in ("XDG_SESSION_TYPE", "WAYLAND_DISPLAY", "DISPLAY"):
        monkeypatch.delenv(variable, raising=False)
    assert screen.session_type() == "aucun"
    with pytest.raises(UnavailableError, match="Aucun écran"):
        await capture()
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    assert screen.session_type() == "wayland"

    def broken() -> bytes:
        raise RuntimeError("bus fermé")

    monkeypatch.setattr(screen, "_capture_portal", broken)
    with pytest.raises(UnavailableError, match=r"Capture d'écran impossible \(RuntimeError\)"):
        await capture()


def budget_capture() -> bytes:
    image = Image.new("RGB", (1280, 800), (245, 246, 248))
    raw = io.BytesIO()
    image.save(raw, "PNG")
    return raw.getvalue()


def vision_script(request: LLMRequest) -> FakeReply:
    images = [i for m in request.messages for i in m.images]
    if images and "capture de l'écran" in request.messages[0].content:
        return FakeReply(text="Un tableur ouvert : budget d'octobre, total 1 045 €.")
    return FakeReply(text="?")


async def _look(services: Services, mode: str) -> tuple[str, dict[str, Any]]:
    async def grab() -> bytes:
        return budget_capture()

    tool = LookAtScreen(services.router, lambda: mode, grab)  # type: ignore[arg-type, return-value]
    out = await tool.run(tool.parse({"question": "Quel est le total ?"}), None)  # type: ignore[arg-type]
    return out.text, out.data


def test_reading_the_screen_stays_local_by_default(
    client: TestClient, services: Services, llm: dict[str, FakeProvider]
) -> None:
    llm["ollama"]._configured = True
    llm["ollama"]._script = vision_script
    llm["openrouter"]._configured = True
    llm["openrouter"]._script = vision_script
    llm["deepseek"]._script = vision_script
    assert client.get("/v1/settings").json()["screen_vision"] == "local"
    assert client.portal is not None
    text, data = client.portal.call(_look, services, "local")
    assert "1 045 €" in text
    assert data["mode"] == "local"
    assert llm["openrouter"].requests == []  # l'image n'est pas partie en ligne
    assert llm["deepseek"].requests == []
    request, _ = llm["ollama"].requests[-1]
    assert request.messages[1].images[0].media_type == "image/jpeg"

    text, data = client.portal.call(_look, services, "en_ligne")
    assert data["mode"] == "en_ligne"
    # En ligne, seulement si tu l'as choisi : la vision de DeepSeek d'abord.
    assert data["modele"] == "deepseek-v4-flash-vision-exp"
    assert llm["openrouter"].requests == []


def test_deepseek_down_the_screen_is_read_by_openrouter(
    client: TestClient, services: Services, llm: dict[str, FakeProvider]
) -> None:
    llm["deepseek"]._script = lambda _: FakeReply(error=RateLimitedError("429"))
    llm["openrouter"]._configured = True
    llm["openrouter"]._script = vision_script
    assert client.portal is not None
    text, data = client.portal.call(_look, services, "en_ligne")
    assert "1 045 €" in text
    assert data["mode"] == "en_ligne"
    assert llm["openrouter"].requests


def test_a_saturated_online_model_falls_back_to_a_local_reading(
    client: TestClient, services: Services, llm: dict[str, FakeProvider]
) -> None:
    # Offre gratuite saturée : l'écran est lu en local, avec l'image réduite pour lui.
    llm["ollama"]._configured = True
    llm["ollama"]._script = vision_script
    llm["openrouter"]._configured = True
    llm["openrouter"]._script = lambda _: FakeReply(error=RateLimitedError("429"))
    llm["deepseek"]._script = lambda _: FakeReply(error=RateLimitedError("429"))
    assert client.portal is not None
    text, data = client.portal.call(_look, services, "en_ligne")
    assert "1 045 €" in text
    assert data["mode"] == "local"
    online, _ = llm["openrouter"].requests[-1]
    local, _ = llm["ollama"].requests[-1]
    assert len(llm["ollama"].requests) == 1  # le modèle local n'a vu que l'image réduite
    sizes = []
    for sent in (online, local):
        jpeg = base64.b64decode(sent.messages[1].images[0].data_base64)
        with Image.open(io.BytesIO(jpeg)) as image:
            sizes.append(max(image.size))
    assert sizes == [1280, 768]
