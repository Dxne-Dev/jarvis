"""Téléchargement de modèles locaux, vérifiés par empreinte SHA-256 avant d'être utilisés."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import anyio
import anyio.to_thread
import httpx

from ojarvis.core.logs import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class PinnedFile:
    url: str
    sha256: str


class ChecksumError(RuntimeError):
    """Le fichier reçu n'a pas l'empreinte attendue : il est supprimé, jamais chargé."""


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def files_present(folder: Path, files: Mapping[str, PinnedFile]) -> bool:
    return all((folder / name).is_file() for name in files)


async def fetch_pinned(
    client: httpx.AsyncClient,
    folder: Path,
    files: Mapping[str, PinnedFile],
    *,
    on_progress: Callable[[str, int, int | None], None] | None = None,
) -> None:
    """Télécharge les fichiers absents dans `folder`, en passant par un fichier `.part`."""
    await anyio.Path(folder).mkdir(parents=True, exist_ok=True)
    for name, pinned in files.items():
        target = folder / name
        if await anyio.Path(target).is_file():
            continue
        partial = target.with_name(target.name + ".part")
        log.info("model_download", file=name, folder=folder.name)
        async with client.stream(
            "GET", pinned.url, follow_redirects=True, timeout=httpx.Timeout(30.0, read=120.0)
        ) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length", 0)) or None
            received = 0
            with partial.open("wb") as handle:
                async for chunk in response.aiter_bytes(1 << 20):
                    handle.write(chunk)
                    received += len(chunk)
                    if on_progress is not None:
                        on_progress(name, received, total)
        actual = await anyio.to_thread.run_sync(sha256_of, partial)
        if actual != pinned.sha256:
            partial.unlink(missing_ok=True)
            raise ChecksumError(f"empreinte inattendue pour {name}")
        partial.replace(target)
