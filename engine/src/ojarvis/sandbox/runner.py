"""Bac à sable pour le code non fiable : éphémère, sans réseau, limité, toujours nettoyé.

Docker d'abord (`python:3.12-alpine`, aucun réseau, système de fichiers en lecture seule,
utilisateur sans droits, 1 processeur, 256 Mo, 64 processus, 10 s). À défaut, bubblewrap
(espaces de noms Linux, sans réseau) avec des limites posées par `prlimit`.
"""

from __future__ import annotations

import asyncio
import contextlib
import shutil
import time
import uuid
from dataclasses import dataclass

from ojarvis.core.logs import get_logger

log = get_logger(__name__)

IMAGE = "python:3.12-alpine"
MAX_OUTPUT = 64_000


@dataclass(frozen=True)
class SandboxResult:
    stdout: str
    stderr: str
    exit_code: int | None
    timed_out: bool
    backend: str
    duration_ms: float


class SandboxUnavailableError(RuntimeError):
    """Ni Docker ni bubblewrap : le code n'est pas exécuté."""


def _decode(data: bytes) -> str:
    text = data[:MAX_OUTPUT].decode("utf-8", "replace")
    return text + ("\n[…sortie tronquée]" if len(data) > MAX_OUTPUT else "")


class SandboxRunner:
    def __init__(
        self,
        *,
        timeout_s: float = 10.0,
        memory_mb: int = 256,
        prefer: tuple[str, ...] = ("docker", "bubblewrap"),
    ) -> None:
        self.timeout_s = timeout_s
        self.memory_mb = memory_mb
        self._prefer = prefer
        self._backend: str | None = None
        self._checked = False

    async def backend(self) -> str | None:
        """Le meilleur isolement disponible sur la machine (vérifié une fois)."""
        if self._checked:
            return self._backend
        self._checked = True
        for name in self._prefer:
            if name == "docker" and await self._docker_ready():
                self._backend = "docker"
                break
            if name == "bubblewrap" and await self._bubblewrap_ready():
                self._backend = "bubblewrap"
                break
        log.info("sandbox_backend", backend=self._backend)
        return self._backend

    @staticmethod
    async def _docker_ready() -> bool:
        """Docker répond et l'image du bac à sable est là (jamais de téléchargement surprise)."""
        docker = shutil.which("docker")
        if docker is None:
            return False
        try:
            process = await asyncio.create_subprocess_exec(
                docker,
                "image",
                "inspect",
                IMAGE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            return await asyncio.wait_for(process.wait(), 10) == 0
        except (OSError, TimeoutError):
            return False

    @staticmethod
    async def _bubblewrap_ready() -> bool:
        """Installé ne suffit pas : certains systèmes interdisent les espaces de noms."""
        bwrap = shutil.which("bwrap")
        if bwrap is None or shutil.which("prlimit") is None:
            return False
        probe = [
            bwrap,
            "--unshare-all",
            "--die-with-parent",
            "--ro-bind",
            "/usr",
            "/usr",
            "--symlink",
            "usr/lib",
            "/lib",
            "--symlink",
            "usr/lib64",
            "/lib64",
            "--symlink",
            "usr/bin",
            "/bin",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "/usr/bin/true",
        ]
        try:
            process = await asyncio.create_subprocess_exec(
                *probe, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
            )
            return await asyncio.wait_for(process.wait(), 10) == 0
        except (OSError, TimeoutError):
            return False

    def _docker_command(self, name: str) -> list[str]:
        memory = f"{self.memory_mb}m"
        return [
            shutil.which("docker") or "docker",
            "run",
            "--rm",
            "-i",
            "--name",
            name,
            "--network",
            "none",
            "--cpus",
            "1",
            "--memory",
            memory,
            "--memory-swap",
            memory,
            "--pids-limit",
            "64",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,size=64m,mode=1777",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            "65534:65534",
            "--workdir",
            "/tmp",
            "-e",
            "PYTHONDONTWRITEBYTECODE=1",
            IMAGE,
            "python",
            "-I",
            "-",
        ]

    def _bubblewrap_command(self) -> list[str]:
        memory = str(self.memory_mb * 2 * 1024 * 1024)  # espace d'adressage : marge pour Python
        return [
            shutil.which("bwrap") or "bwrap",
            "--unshare-all",
            "--die-with-parent",
            "--new-session",
            "--cap-drop",
            "ALL",
            "--ro-bind",
            "/usr",
            "/usr",
            "--symlink",
            "usr/lib",
            "/lib",
            "--symlink",
            "usr/lib64",
            "/lib64",
            "--symlink",
            "usr/bin",
            "/bin",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
            "--chdir",
            "/tmp",
            "--clearenv",
            "--setenv",
            "PATH",
            "/usr/bin",
            "--setenv",
            "HOME",
            "/tmp",
            "--",
            "/usr/bin/prlimit",
            f"--as={memory}",
            f"--cpu={int(self.timeout_s) + 1}",
            "--nproc=64",
            "--fsize=10485760",
            "/usr/bin/python3",
            "-I",
            "-",
        ]

    async def run_python(self, code: str, *, timeout_s: float | None = None) -> SandboxResult:
        backend = await self.backend()
        if backend is None:
            raise SandboxUnavailableError("Aucun bac à sable disponible (Docker ou bubblewrap).")
        limit = timeout_s or self.timeout_s
        name = f"ojarvis-sbx-{uuid.uuid4().hex[:12]}"
        command = self._docker_command(name) if backend == "docker" else self._bubblewrap_command()
        start = time.perf_counter()
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        timed_out = False
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(code.encode()), limit)
        except TimeoutError:
            timed_out = True
            stdout, stderr = b"", "Temps d'exécution dépassé.".encode()
        finally:
            # Nettoyage garanti, même en cas d'erreur ou d'annulation.
            if process.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
                with contextlib.suppress(Exception):
                    await process.wait()
            if backend == "docker":
                await self._remove_container(name)
        return SandboxResult(
            stdout=_decode(stdout),
            stderr=_decode(stderr),
            exit_code=None if timed_out else process.returncode,
            timed_out=timed_out,
            backend=backend,
            duration_ms=round((time.perf_counter() - start) * 1000, 1),
        )

    @staticmethod
    async def _remove_container(name: str) -> None:
        docker = shutil.which("docker")
        if docker is None:
            return
        with contextlib.suppress(Exception):
            process = await asyncio.create_subprocess_exec(
                docker,
                "rm",
                "-f",
                name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(process.wait(), 15)


async def docker_available() -> bool:
    """Le démon Docker répond (pour les serveurs MCP, qui ont leurs propres images)."""
    docker = shutil.which("docker")
    if docker is None:
        return False
    try:
        process = await asyncio.create_subprocess_exec(
            docker,
            "version",
            "--format",
            "{{.Server.Version}}",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        return await asyncio.wait_for(process.wait(), 10) == 0
    except (OSError, TimeoutError):
        return False
