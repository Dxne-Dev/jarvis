"""Téléchargement de modèles locaux, vérifiés par empreinte SHA-256 avant d'être utilisés."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
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
    #: Taille en octets, pour afficher ce qui reste à télécharger.
    size: int | None = None


#: Attente avant chaque nouvel essai quand la connexion coupe.
RETRY_DELAYS_S: tuple[float, ...] = (2.0, 5.0, 15.0, 30.0)


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
    retry_delays: Sequence[float] = RETRY_DELAYS_S,
) -> None:
    """Télécharge les fichiers absents dans `folder`, en passant par un fichier `.part`.

    Une coupure ne fait pas tout recommencer : l'essai suivant reprend le `.part` où il
    s'est arrêté (requête `Range`).
    """
    await anyio.Path(folder).mkdir(parents=True, exist_ok=True)
    for name, pinned in files.items():
        target = folder / name
        if await anyio.Path(target).is_file():
            continue
        partial = target.with_name(target.name + ".part")
        log.info("model_download", file=name, folder=folder.name)
        for attempt, delay in enumerate((*retry_delays, None)):
            try:
                await _fetch_part(client, pinned, partial, name, on_progress)
                break
            except (httpx.TransportError, _RetryableStatus) as exc:
                if delay is None:
                    raise
                log.warning("model_download_retry", file=name, attempt=attempt + 1, error=str(exc))
                await anyio.sleep(delay)
        actual = await anyio.to_thread.run_sync(sha256_of, partial)
        if actual != pinned.sha256:
            partial.unlink(missing_ok=True)
            raise ChecksumError(f"empreinte inattendue pour {name}")
        partial.replace(target)


class _RetryableStatus(httpx.HTTPStatusError):
    """Erreur passagère du serveur (5xx, 429) : on réessaie."""


async def _fetch_part(
    client: httpx.AsyncClient,
    pinned: PinnedFile,
    partial: Path,
    name: str,
    on_progress: Callable[[str, int, int | None], None] | None,
) -> None:
    part = anyio.Path(partial)
    offset = (await part.stat()).st_size if await part.is_file() else 0
    if pinned.size is not None and offset >= pinned.size:
        return  # déjà entier : l'empreinte tranchera
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    async with client.stream(
        "GET",
        pinned.url,
        headers=headers,
        follow_redirects=True,
        timeout=httpx.Timeout(30.0, read=120.0),
    ) as response:
        if response.status_code == 416 and offset:
            return  # rien après `offset` : le `.part` est complet
        if response.status_code >= 500 or response.status_code == 429:
            raise _RetryableStatus(
                f"HTTP {response.status_code}", request=response.request, response=response
            )
        response.raise_for_status()
        if response.status_code != 206:
            offset = 0  # le serveur renvoie tout le fichier : on repart de zéro
        length = int(response.headers.get("content-length", 0))
        total = pinned.size or ((offset + length) if length else None)
        received = offset
        with partial.open("ab" if offset else "wb") as handle:
            async for chunk in response.aiter_bytes():
                handle.write(chunk)
                received += len(chunk)
                if on_progress is not None:
                    on_progress(name, received, total)
