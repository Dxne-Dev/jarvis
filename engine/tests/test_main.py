"""Cycle de vie réel du moteur, lancé comme le fait l'app : jeton sur stdin, READY sur stdout."""

from __future__ import annotations

import json
import os
import selectors
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from ojarvis.__main__ import EXIT_BAD_TOKEN, EXIT_LOCKED, READY_PREFIX, acquire_lock, parse_args

TOKEN = "s" * 43


def engine_env(home: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["OJARVIS_HOME"] = str(home)
    # Trousseau neutre : le test ne touche jamais au vrai trousseau de l'utilisateur.
    env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
    env.pop("OJARVIS_DOTENV", None)
    return env


def start_engine(home: Path) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, "-m", "ojarvis"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=engine_env(home),
    )


def read_ready(proc: subprocess.Popen[bytes], timeout: float = 30.0) -> dict[str, int]:
    assert proc.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    buffer = b""
    while time.monotonic() < deadline:
        if not selector.select(timeout=0.2):
            continue
        chunk = os.read(proc.stdout.fileno(), 4096)
        if not chunk:
            break
        buffer += chunk
        for line in buffer.decode().splitlines():
            if line.startswith(READY_PREFIX):
                info: dict[str, int] = json.loads(line[len(READY_PREFIX) :])
                return info
    raise AssertionError(f"pas de ligne READY : {buffer!r}")


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[tuple[subprocess.Popen[bytes], dict[str, int]]]:
    proc = start_engine(tmp_path)
    assert proc.stdin is not None
    proc.stdin.write(TOKEN.encode() + b"\n")
    proc.stdin.flush()
    try:
        yield proc, read_ready(proc)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(5)


def test_handshake_serves_and_stops_when_stdin_closes(
    engine: tuple[subprocess.Popen[bytes], dict[str, int]],
) -> None:
    proc, info = engine
    assert info["pid"] == proc.pid
    base = f"http://127.0.0.1:{info['port']}"
    assert httpx.get(f"{base}/health").json() == {"status": "ok"}
    status = httpx.get(f"{base}/v1/status", headers={"Authorization": f"Bearer {TOKEN}"}).json()
    assert status["keyring_error"] is not None  # trousseau neutre : dégradé, mais vivant
    assert httpx.get(f"{base}/v1/status").status_code == 401
    assert proc.stdin is not None
    proc.stdin.close()
    assert proc.wait(15) == 0


def test_engine_listens_only_on_loopback(
    engine: tuple[subprocess.Popen[bytes], dict[str, int]],
) -> None:
    _, info = engine
    out = subprocess.run(  # noqa: S603
        ["ss", "-ltnH", f"sport = :{info['port']}"],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    local_addresses = [line.split()[3] for line in out.splitlines() if line.strip()]
    assert local_addresses == [f"127.0.0.1:{info['port']}"]


def test_second_engine_on_same_data_is_refused(
    engine: tuple[subprocess.Popen[bytes], dict[str, int]], tmp_path: Path
) -> None:
    second = start_engine(tmp_path)
    _, _ = second.communicate(TOKEN.encode() + b"\n", timeout=30)
    assert second.returncode == EXIT_LOCKED


def test_short_token_is_refused(tmp_path: Path) -> None:
    proc = start_engine(tmp_path)
    proc.communicate(b"court\n", timeout=30)
    assert proc.returncode == EXIT_BAD_TOKEN


def test_parse_args_defaults() -> None:
    args = parse_args([])
    assert args.port == 0
    assert args.token_env is None
    assert not args.dev


def test_lock_is_exclusive(tmp_path: Path) -> None:
    first = acquire_lock(tmp_path / "x.lock")
    assert first is not None
    assert acquire_lock(tmp_path / "x.lock") is None
    first.close()
    again = acquire_lock(tmp_path / "x.lock")
    assert again is not None
    again.close()
