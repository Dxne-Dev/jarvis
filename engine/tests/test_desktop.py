"""Contrôle du PC : applications, écran, fichiers — désactivé par défaut, sous la porte."""

from __future__ import annotations

import asyncio
import io
import shutil
import struct
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from ojarvis.core.errors import InvalidInputError, NotFoundError
from ojarvis.desktop import apps as applications
from ojarvis.desktop.screen import capture, shrink
from ojarvis.llm.providers.fake import FakeProvider, FakeReply
from ojarvis.llm.structured import TOOL_NAME
from ojarvis.llm.types import LLMRequest, ToolCall
from ojarvis.permissions.gate import OsControlDisabledError
from ojarvis.services import Services
from ojarvis.tools.base import Level
from ojarvis.tools.desktop import LookAtScreen
from tests.test_chat import read_sse

ENTRY = """[Desktop Entry]
Type=Application
Name={name}
{extra}
Exec={exec}
"""


def write_app(folder: Path, app_id: str, name: str, exec_: str, extra: str = "") -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{app_id}.desktop").write_text(
        ENTRY.format(name=name, exec=exec_, extra=extra), encoding="utf-8"
    )


@pytest.fixture
def menu(tmp_path: Path) -> Path:
    folder = tmp_path / "applications"
    write_app(
        folder,
        "org.gnome.Calculator",
        "Calculator",
        "gnome-calculator %U",
        "Name[fr]=Calculatrice\nKeywords=calcul;maths;",
    )
    write_app(folder, "firefox", "Firefox", "env MOZ_ENABLE_WAYLAND=1 /usr/lib/firefox/firefox %u")
    write_app(folder, "cache", "Caché", "cache", "NoDisplay=true")
    write_app(folder, "kde-only", "KDE seulement", "kde", "OnlyShowIn=KDE;")
    write_app(
        folder,
        "org.gnome.TextEditor",
        "Text Editor",
        "gnome-text-editor",
        "Name[fr]=Éditeur de texte",
    )
    return folder


def test_the_menu_index_reads_desktop_entries(menu: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "ubuntu:GNOME")
    apps = applications.index([menu])
    assert sorted(apps) == ["firefox", "org.gnome.Calculator", "org.gnome.TextEditor"]
    calc = apps["org.gnome.Calculator"]
    assert calc.name == "Calculatrice"
    assert calc.exec_name == "gnome-calculator"
    assert apps["firefox"].exec_name == "firefox"  # « env VAR=… » et chemin retirés
    assert applications.find(apps, "calculatrice").id == "org.gnome.Calculator"
    assert applications.find(apps, "CALCUL").id == "org.gnome.Calculator"
    assert applications.find(apps, "editeur").id == "org.gnome.TextEditor"  # sans accent
    assert applications.find(apps, "maths").id == "org.gnome.Calculator"  # mot-clé
    with pytest.raises(NotFoundError, match="Aucune application"):
        applications.find(apps, "photoshop")
    with pytest.raises(NotFoundError, match="Plusieurs applications"):
        applications.find(apps, "gnome")


def write_mo(path: Path, catalog: dict[str, str]) -> None:
    """Un catalogue gettext minimal (format .mo, comme `msgfmt`)."""
    entries = {"": "Content-Type: text/plain; charset=UTF-8\n", **catalog}
    keys = sorted(entries)
    ids = b"".join(k.encode() + b"\0" for k in keys)
    strs = b"".join(entries[k].encode() + b"\0" for k in keys)
    start = 7 * 4 + 16 * len(keys)
    table_ids, table_strs, at_id, at_str = [], [], start, start + len(ids)
    for key in keys:
        table_ids += [len(key.encode()), at_id]
        table_strs += [len(entries[key].encode()), at_str]
        at_id += len(key.encode()) + 1
        at_str += len(entries[key].encode()) + 1
    header = struct.pack("<7I", 0x950412DE, 0, len(keys), 28, 28 + 8 * len(keys), 0, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        header
        + struct.pack(f"<{len(table_ids)}I", *table_ids)
        + struct.pack(f"<{len(table_strs)}I", *table_strs)
        + ids
        + strs
    )


def test_names_are_translated_like_the_ubuntu_menu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Sous Ubuntu, la plupart des entrées n'ont pas de Name[fr] : leur nom passe par gettext.
    monkeypatch.setenv("LANGUAGE", "")
    monkeypatch.setenv("LANG", "fr_FR.UTF-8")
    folder = tmp_path / "applications"
    domain = "X-Ubuntu-Gettext-Domain=gnome-calculator\nKeywords=calculation;arithmetic;"
    write_app(folder, "org.gnome.Calculator", "Calculator", "gnome-calculator", domain)
    browser = "GenericName=Web Browser\nGenericName[fr]=Navigateur web"
    write_app(folder, "firefox", "Firefox", "firefox", browser)
    write_app(folder, "chromium", "Chromium", "chromium", browser)
    sneaky = "X-GNOME-Gettext-Domain=../../../tmp/piege"
    write_app(folder, "piege", "Piège", "piege", sneaky)
    locales = tmp_path / "locale"
    write_mo(
        locales / "fr" / "LC_MESSAGES" / "gnome-calculator.mo",
        {"Calculator": "Calculatrice", "calculation;arithmetic;": "calcul;arithmétique;"},
    )
    apps = applications.index([folder], locale_dirs=(tmp_path / "absent", locales))
    calc = apps["org.gnome.Calculator"]
    assert (calc.name, calc.aliases) == ("Calculatrice", ("Calculator",))
    assert calc.keywords == ("calcul", "arithmétique")
    assert applications.find(apps, "calculatrice").id == "org.gnome.Calculator"
    assert applications.find(apps, "calculator").id == "org.gnome.Calculator"  # nom d'origine
    assert applications.find(apps, "arithmetique").id == "org.gnome.Calculator"
    assert apps["piege"].name == "Piège"  # un domaine qui sort du dossier est ignoré
    with pytest.raises(NotFoundError, match=r"Plusieurs applications.*Chromium, Firefox"):
        applications.find(apps, "navigateur")  # Jarvis te demandera lequel


def test_closing_only_targets_your_own_matching_processes(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    for pid, command in (
        (101, b"/usr/bin/gnome-calculator\0"),
        (102, b"/usr/bin/python3\0x"),
        (103, b"gnome-calculator\0--x"),
    ):
        (proc / str(pid)).mkdir(parents=True)
        (proc / str(pid) / "cmdline").write_bytes(command)
    assert applications._processes("gnome-calculator", proc) == [101, 103]
    # Jamais les processus protégés (session, Jarvis, interpréteurs partagés).
    assert applications._processes("python3", proc) == []
    assert applications._processes("gnome-shell", proc) == []
    assert applications._processes("flatpak", proc) == []


async def test_a_running_app_is_closed_with_sigterm(tmp_path: Path) -> None:
    name = "ojarvis-test-app-close"
    # Un Python qui se présente sous ce nom (argv[0]) : c'est ce que lit /proc/<pid>/cmdline.
    program = (
        f"import os, sys; os.execv(sys.executable, [{name!r}, '-c', 'import time; time.sleep(30)'])"
    )
    process = await asyncio.create_subprocess_exec(sys.executable, "-c", program)
    try:
        entry = applications.AppEntry("test.app", "Appli de test", name, tmp_path / "x.desktop")
        for _ in range(50):
            if applications._processes(name):
                break
            await asyncio.sleep(0.05)
        closed, left = await applications.close(entry, wait_s=3)
        assert (closed, left) == (1, 0)
        assert await asyncio.wait_for(process.wait(), 3) == -15  # SIGTERM
        with pytest.raises(NotFoundError, match="n'est pas ouverte"):
            await applications.close(entry)
    finally:
        if process.returncode is None:
            process.kill()


async def test_apps_are_launched_by_id_without_a_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = tmp_path / "calls"
    fake = tmp_path / "gtk-launch"
    fake.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > {calls}\n')
    fake.chmod(0o755)
    monkeypatch.setattr("shutil.which", lambda name: str(fake) if name == "gtk-launch" else None)
    entry = applications.AppEntry(
        "org.gnome.Calculator", "Calculatrice", "gnome-calculator", tmp_path
    )
    await applications.launch(entry)
    assert calls.read_text() == "org.gnome.Calculator\n"


# ---------------------------------------------------------------------- écran


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
    assert client.get("/v1/settings").json()["screen_vision"] == "local"
    assert client.portal is not None
    text, data = client.portal.call(_look, services, "local")
    assert "1 045 €" in text
    assert data["mode"] == "local"
    assert llm["openrouter"].requests == []  # l'image n'est pas partie en ligne
    request, _ = llm["ollama"].requests[-1]
    assert request.messages[1].images[0].media_type == "image/jpeg"

    text, data = client.portal.call(_look, services, "en_ligne")
    assert data["mode"] == "en_ligne"
    assert llm["openrouter"].requests  # en ligne : seulement si tu l'as choisi


# ---------------------------------------------------------------------- porte et chat


def test_os_control_is_off_by_default_and_gated(client: TestClient, services: Services) -> None:
    assert client.get("/v1/settings").json()["os_control_enabled"] is False
    with pytest.raises(OsControlDisabledError, match="désactivé"):
        services.gate.check("ouvrir_application", {"nom": "calculatrice"})
    names = {s.name for s in services.tools.specs(max_level=Level.DETRUIRE, os_control=False)}
    assert "ouvrir_application" not in names
    assert "regarder_ecran" not in names
    catalog = {t["name"]: t for t in client.get("/v1/tools").json()}
    assert catalog["ouvrir_application"]["level"] == 2
    assert catalog["regarder_ecran"]["level"] == 1
    assert catalog["ouvrir_application"]["os_control"] is True


def test_an_app_opens_only_after_validation(
    client: TestClient,
    services: Services,
    llm: dict[str, FakeProvider],
    menu: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del services
    calls = menu.parent / "launched"
    fake = menu.parent / "gtk-launch"
    fake.write_text(f'#!/bin/sh\nprintf "%s" "$1" > {calls}\n')
    fake.chmod(0o755)
    real_which = shutil.which
    monkeypatch.setattr(
        "shutil.which", lambda name: str(fake) if name == "gtk-launch" else real_which(name)
    )
    monkeypatch.setattr("ojarvis.desktop.apps.application_dirs", lambda: [menu])
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")

    def script(request: LLMRequest) -> FakeReply:
        if request.tools and request.tools[0].name == TOOL_NAME:
            return FakeReply(tool_calls=[ToolCall("m", TOOL_NAME, {"faits": []})])
        if "titre" in request.messages[0].content:
            return FakeReply(text="Calculatrice")
        if any(m.role == "tool" for m in request.messages):
            return FakeReply(text="Je l'ouvre dès que tu valides.")
        return FakeReply(tool_calls=[ToolCall("o", "ouvrir_application", {"nom": "calculatrice"})])

    llm["deepseek"]._script = script
    # Désactivé : l'outil n'est même pas proposé, et un appel forgé est refusé.
    events = read_sse(client.post("/v1/chat", json={"text": "Ouvre la calculatrice"}).text)
    failed = [d for e, d in events if e == "tool" and d["status"] == "failed"]
    assert failed
    assert "désactivé" in failed[0]["error"]

    assert client.patch("/v1/settings", json={"os_control_enabled": True}).status_code == 200
    events = read_sse(client.post("/v1/chat", json={"text": "Ouvre la calculatrice"}).text)
    plan = next(d for e, d in events if e == "plan")
    assert (
        plan["steps"][0]["description"]
        == "Ouvrir l'application Calculatrice (org.gnome.Calculator)"
    )
    assert not calls.exists()  # rien avant ta validation
    client.post(f"/v1/plans/{plan['id']}/approve", json={})
    for _ in range(100):
        if calls.exists():
            break
        time.sleep(0.05)
    assert calls.read_text() == "org.gnome.Calculator"


async def test_moving_files_keeps_the_guards(tmp_path: Path) -> None:
    from ojarvis.tools.base import ToolContext  # noqa: PLC0415
    from ojarvis.tools.desktop import CopyFile, MakeDir, MoveFile  # noqa: PLC0415

    home = tmp_path / "home"
    (home / "notes").mkdir(parents=True)
    (home / "notes" / "a.txt").write_text("a")
    (home / ".ssh").mkdir()
    ctx = ToolContext(http=None, secret=lambda _: None, home=home)  # type: ignore[arg-type]
    move, copy, mkdir = MoveFile(), CopyFile(), MakeDir()
    await mkdir.run(mkdir.parse({"chemin": "archives/2026"}), ctx)
    await copy.run(copy.parse({"source": "notes/a.txt", "destination": "archives/2026"}), ctx)
    await move.run(move.parse({"source": "notes/a.txt", "destination": "notes/b.txt"}), ctx)
    assert (home / "archives/2026/a.txt").read_text() == "a"
    assert (home / "notes/b.txt").exists()
    with pytest.raises(InvalidInputError, match="existe déjà"):
        await copy.run(
            copy.parse({"source": "notes/b.txt", "destination": "archives/2026/a.txt"}), ctx
        )
    with pytest.raises(InvalidInputError, match="protégé"):
        await move.run(move.parse({"source": "notes/b.txt", "destination": ".ssh/b.txt"}), ctx)
    with pytest.raises(InvalidInputError):
        await copy.run(copy.parse({"source": "/etc/passwd", "destination": "notes/p"}), ctx)
    assert (home / "notes/b.txt").read_text() == "a"
