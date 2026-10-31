"""Contrôle du PC : les applications (menu, lancement, fermeture) et les adresses web.

La capture de l'écran est dans `test_screen_capture.py`, la porte dans `test_os_control.py`.
"""

from __future__ import annotations

import asyncio
import functools
import os
import struct
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ojarvis.core.errors import InvalidInputError, NotFoundError
from ojarvis.desktop import apps as applications
from ojarvis.tools.desktop import AppCatalog, CloseApp, OpenUrl, RunningApps, UrlArgs
from tests.conftest import write_app


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


def fake_process(proc: Path, pid: int, argv0: str, exe: Path) -> None:
    (proc / str(pid)).mkdir(parents=True)
    (proc / str(pid) / "cmdline").write_bytes(argv0.encode() + b"\0--x")
    os.symlink(exe, proc / str(pid) / "exe")


async def test_a_script_launched_app_is_found_by_its_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Chrome : `google-chrome` est un script qui lance `chrome`, rangé dans le même dossier.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    chrome_dir = tmp_path / "opt" / "google" / "chrome"
    chrome_dir.mkdir(parents=True)
    (chrome_dir / "google-chrome").write_text("#!/bin/sh\nexec chrome\n")
    folder = tmp_path / "applications"
    write_app(folder, "google-chrome", "Google Chrome", f"{chrome_dir}/google-chrome %U")
    write_app(folder, "youtube", "YouTube", f"{chrome_dir}/google-chrome --app-id=abc")
    write_app(folder, "calc", "Calculatrice", "gnome-calculator")
    proc = tmp_path / "proc"
    fake_process(proc, 201, "/opt/google/chrome/chrome", chrome_dir / "chrome")
    fake_process(proc, 202, "/opt/google/chrome/crashpad", chrome_dir / "crashpad")
    fake_process(proc, 203, "python3", chrome_dir / "python3")  # protégé, même rangé là
    fake_process(proc, 204, "/usr/bin/gnome-calculator", Path("/usr/bin/gnome-calculator"))
    fake_process(proc, 205, "/usr/bin/vim", Path("/usr/bin/vim"))
    apps = applications.index([folder])
    chrome = apps["google-chrome"]
    assert applications.app_root(chrome) == chrome_dir
    assert applications.app_root(apps["calc"]) is None  # un vrai programme : son nom suffit
    found = {e.id: pids for e, pids in applications.running(apps, proc)}
    assert found == {"google-chrome": [201, 202], "youtube": [201, 202], "calc": [204]}
    assert [e.id for e in applications.same_program(apps, chrome)] == ["youtube"]

    # Ce que tu lis avant de valider : fermer YouTube ferme aussi Chrome.
    catalog = AppCatalog(lambda: apps)
    close = CloseApp(catalog)
    assert close.describe(close.parse({"nom": "youtube"})) == (
        "Fermer l'application YouTube (youtube) — même programme que Google Chrome : "
        "tout se fermera ensemble"
    )
    monkeypatch.setattr(applications, "running", functools.partial(applications.running, proc=proc))
    tool = RunningApps(catalog)
    out = await tool.run(tool.parse({}), None)  # type: ignore[arg-type]
    assert out.text.splitlines() == [
        "Calculatrice (calc) — 1 processus",
        "Google Chrome (google-chrome), YouTube (youtube) — même programme, 2 processus",
    ]


def test_a_script_in_a_shared_folder_gives_no_app_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    (home / "Téléchargements").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    for script in (home / "lance.sh", home / "Téléchargements" / "lance.sh"):
        script.write_text("#!/bin/sh\n")
        entry = applications.AppEntry("x", "X", "lance.sh", script, command=str(script))
        assert applications.app_root(entry) is None  # tout un dossier personnel : trop large


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
    assert calls.read_text() == "--\norg.gnome.Calculator\n"


async def test_an_address_opens_in_your_browser_without_a_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = tmp_path / "calls"
    fake = tmp_path / "xdg-open"
    fake.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > {calls}\n')
    fake.chmod(0o755)
    monkeypatch.setattr("shutil.which", lambda name: str(fake) if name == "xdg-open" else None)
    tool = OpenUrl()
    args = UrlArgs(adresse=" https://github.com/octavebahoun/gouvra/pull/6 ")
    assert tool.describe(args).endswith("gouvra/pull/6 dans ton navigateur")
    out = await tool.run(args, SimpleNamespace())  # type: ignore[arg-type]
    assert calls.read_text() == "https://github.com/octavebahoun/gouvra/pull/6\n"
    assert "Ouvert dans ton navigateur" in out.text


@pytest.mark.parametrize(
    "raw", ["file:///etc/passwd", "javascript:alert(1)", "--help", "https://", "ftp://exemple.fr"]
)
async def test_only_web_addresses_reach_the_browser(
    raw: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = tmp_path / "calls"
    fake = tmp_path / "xdg-open"
    fake.write_text(f"#!/bin/sh\ntouch {calls}\n")
    fake.chmod(0o755)
    monkeypatch.setattr("shutil.which", lambda name: str(fake) if name == "xdg-open" else None)
    with pytest.raises(InvalidInputError, match="http et https"):
        await OpenUrl().run(UrlArgs(adresse=raw), SimpleNamespace())  # type: ignore[arg-type]
    assert not calls.exists()
