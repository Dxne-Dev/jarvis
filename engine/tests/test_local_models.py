"""Modèles locaux : reprise après coupure, nouvel essai, import de fichiers faits à la main."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from pathlib import Path

import anyio
import httpx
import pytest
from fastapi.testclient import TestClient

from ojarvis import local_models
from ojarvis.core.downloads import ChecksumError, PinnedFile, fetch_pinned
from ojarvis.local_models import LOCAL_MODELS, ModelSet, import_file
from ojarvis.services import Services

CONTENT = bytes(range(256)) * 40
PINNED = PinnedFile("https://exemple.invalid/model.bin", hashlib.sha256(CONTENT).hexdigest())


class _CutStream(httpx.AsyncByteStream):
    """Envoie le début du fichier puis coupe, comme une connexion qui lâche."""

    def __init__(self, data: bytes) -> None:
        self._data = data

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self._data
        raise httpx.ReadError("connexion coupée")


async def test_a_cut_download_resumes_where_it_stopped(tmp_path: Path) -> None:
    ranges: list[str | None] = []
    half = len(CONTENT) // 2

    def handler(request: httpx.Request) -> httpx.Response:
        ranges.append(request.headers.get("Range"))
        if len(ranges) == 1:
            return httpx.Response(200, stream=_CutStream(CONTENT[:half]))
        start = int(request.headers["Range"].removeprefix("bytes=").removesuffix("-"))
        return httpx.Response(206, content=CONTENT[start:])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await fetch_pinned(client, tmp_path, {"model.bin": PINNED}, retry_delays=(0,))
    assert ranges == [None, f"bytes={half}-"]
    assert (tmp_path / "model.bin").read_bytes() == CONTENT
    assert not (tmp_path / "model.bin.part").exists()


async def test_a_server_ignoring_range_restarts_from_zero(tmp_path: Path) -> None:
    (tmp_path / "model.bin.part").write_bytes(b"debut abime")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Range"] == "bytes=11-"
        return httpx.Response(200, content=CONTENT)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await fetch_pinned(client, tmp_path, {"model.bin": PINNED}, retry_delays=())
    assert (tmp_path / "model.bin").read_bytes() == CONTENT


async def test_a_busy_server_is_retried_then_gives_up(tmp_path: Path) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await fetch_pinned(client, tmp_path, {"model.bin": PINNED}, retry_delays=(0, 0))
    assert calls == 3


async def _chunks(data: bytes) -> AsyncIterator[bytes]:
    for start in range(0, len(data), 1000):
        yield data[start : start + 1000]


@pytest.fixture
def known_model(monkeypatch: pytest.MonkeyPatch) -> ModelSet:
    model = ModelSet("transcription", "Transcription", "faster-whisper-base", {"model.bin": PINNED})
    monkeypatch.setattr(local_models, "LOCAL_MODELS", (model,))
    return model


async def test_an_imported_file_is_recognised_whatever_its_name(
    tmp_path: Path, known_model: ModelSet
) -> None:
    (tmp_path / known_model.folder).mkdir()
    (tmp_path / known_model.folder / "model.bin.part").write_bytes(b"ancien essai")
    imported = await import_file(tmp_path, _chunks(CONTENT))
    assert (imported.key, imported.file) == ("transcription", "model.bin")
    assert (tmp_path / known_model.folder / "model.bin").read_bytes() == CONTENT
    assert not (tmp_path / known_model.folder / "model.bin.part").exists()
    assert [p async for p in anyio.Path(tmp_path).glob(".import-*")] == []


async def test_an_unknown_file_is_refused_and_deleted(
    tmp_path: Path, known_model: ModelSet
) -> None:
    with pytest.raises(ChecksumError, match="aucun modèle"):
        await import_file(tmp_path, _chunks(b"pas un modele"))
    assert [p async for p in anyio.Path(tmp_path).rglob("*")] == []


def test_every_pinned_file_has_a_size() -> None:
    for model in LOCAL_MODELS:
        assert all(pinned.size for pinned in model.files.values()), model.key


def test_the_api_lists_and_imports_models(
    client: TestClient, services: Services, known_model: ModelSet
) -> None:
    listing = client.get("/v1/local-models").json()
    assert [m["key"] for m in listing] == ["transcription"]
    assert listing[0]["folder"] == str(services.models_dir / "faster-whisper-base")
    assert listing[0]["files"][0] == {
        "name": "model.bin",
        "url": PINNED.url,
        "sha256": PINNED.sha256,
        "size": None,
        "present": False,
        "partial": 0,
    }

    refused = client.post("/v1/local-models/import", content=b"autre chose")
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "model_rejected"

    accepted = client.post("/v1/local-models/import", content=CONTENT)
    assert accepted.json() == {
        "key": "transcription",
        "label": "Transcription",
        "file": "model.bin",
        "ready": True,
    }
    assert client.get("/v1/local-models").json()[0]["state"] == "prêt"
    assert client.post("/v1/local-models/retry").status_code == 202


def test_a_voice_failure_says_why_without_the_home_folder() -> None:
    from ojarvis.voice.devices import _describe  # noqa: PLC0415

    home = str(Path.home())
    message = _describe(RuntimeError(f"Unable to open file {home}/.cache/model.bin\ndétail"))
    assert message == (
        "Le pipeline vocal n'a pas pu démarrer "
        "(RuntimeError : Unable to open file ~/.cache/model.bin)."
    )
    assert "libportaudio2" in _describe(OSError("PortAudio library not found"))
    assert "réinstalle" in _describe(ModuleNotFoundError("absent", name="onnxruntime"))
