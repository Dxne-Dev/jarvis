"""Bac à sable : le code tourne isolé (pas de réseau, pas de fichiers perso, temps borné)."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from ojarvis.sandbox.runner import SandboxRunner, SandboxUnavailableError


async def _docker_ok() -> bool:
    return await SandboxRunner._docker_ready()


def _bubblewrap_ok() -> bool:
    return bool(shutil.which("bwrap") and shutil.which("prlimit"))


@pytest.fixture(params=["docker", "bubblewrap"])
async def runner(request: pytest.FixtureRequest) -> SandboxRunner:
    backend: str = request.param
    if backend == "docker" and not await _docker_ok():
        pytest.skip("Docker indisponible")
    if backend == "bubblewrap" and not _bubblewrap_ok():
        pytest.skip("bubblewrap indisponible")
    sandbox = SandboxRunner(prefer=(backend,), timeout_s=20.0)
    if await sandbox.backend() != backend:
        pytest.skip(f"{backend} ne démarre pas ici")
    return sandbox


async def test_code_runs_and_prints(runner: SandboxRunner) -> None:
    result = await runner.run_python("print(sum(range(10)))")
    assert result.stdout.strip() == "45"
    assert result.exit_code == 0
    assert not result.timed_out


async def test_no_network(runner: SandboxRunner) -> None:
    code = (
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 53), timeout=3)\n"
        "    print('connecté')\n"
        "except OSError as e:\n"
        "    print('bloqué')\n"
    )
    result = await runner.run_python(code)
    assert result.stdout.strip() == "bloqué"


async def test_personal_files_are_out_of_reach(runner: SandboxRunner) -> None:
    home = Path.home()
    # Le dossier personnel de la machine n'existe pas dans le bac à sable.
    result = await runner.run_python(f"import os\nprint(os.path.exists({str(home)!r}))")
    assert result.stdout.strip() == "False"


async def test_endless_code_is_stopped_and_cleaned(runner: SandboxRunner) -> None:
    result = await runner.run_python("while True: pass", timeout_s=3.0)
    assert result.timed_out
    assert result.exit_code is None
    if result.backend == "docker":
        process = await asyncio.create_subprocess_exec(
            "docker", "ps", "-aq", "--filter", "name=ojarvis-sbx", stdout=asyncio.subprocess.PIPE
        )
        out, _ = await process.communicate()
        assert out.strip() == b""


async def test_memory_is_bounded(runner: SandboxRunner) -> None:
    result = await runner.run_python("x = bytearray(1024 * 1024 * 1024)\nprint('trop')")
    assert "trop" not in result.stdout
    assert result.exit_code != 0


async def test_without_any_isolation_nothing_runs() -> None:
    sandbox = SandboxRunner(prefer=())
    with pytest.raises(SandboxUnavailableError):
        await sandbox.run_python("print(1)")
