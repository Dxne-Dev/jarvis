"""Embeddings locaux : multilingual-e5-small quantifié, exécuté par ONNX Runtime sur le CPU.

Le modèle (~120 Mo) est téléchargé une fois, vérifié par empreinte SHA-256, puis gardé
en cache. Aucun texte ne quitte la machine pour être vectorisé.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import threading
import unicodedata
from pathlib import Path
from typing import Any, Literal, Protocol

import anyio.to_thread
import httpx
import numpy as np
import numpy.typing as npt

from ojarvis.core.logs import get_logger

log = get_logger(__name__)

Kind = Literal["query", "passage"]
Vectors = npt.NDArray[np.float32]

HF_BASE = "https://huggingface.co/Xenova/multilingual-e5-small/resolve/main"
E5_FILES: dict[str, tuple[str, str]] = {
    "model_quantized.onnx": (
        f"{HF_BASE}/onnx/model_quantized.onnx",
        "f80102d3f2a1229f387d3c81909990d8945513e347b0eab049f7de3c6f98c193",
    ),
    "tokenizer.json": (
        f"{HF_BASE}/tokenizer.json",
        "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39",
    ),
}


class Embedder(Protocol):
    model_id: str
    dim: int

    @property
    def status(self) -> str: ...

    async def embed(self, texts: list[str], kind: Kind) -> Vectors: ...


def _normalize(vectors: npt.NDArray[np.float32]) -> Vectors:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    result: Vectors = (vectors / norms).astype(np.float32)
    return result


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


class E5Embedder:
    model_id = "e5s"
    dim = 384

    def __init__(self, folder: Path, *, threads: int = 2) -> None:
        self.folder = folder
        self._threads = threads
        self._session: Any = None
        self._tokenizer: Any = None
        self._ready = asyncio.Event()
        self._load_lock = asyncio.Lock()
        self._run_lock = threading.Lock()
        self._status = "absent"

    @property
    def status(self) -> str:
        return self._status

    def files_present(self) -> bool:
        return all((self.folder / name).is_file() for name in E5_FILES)

    async def download(self, client: httpx.AsyncClient) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        for name, (url, expected) in E5_FILES.items():
            target = self.folder / name
            if target.is_file():
                continue
            self._status = "téléchargement"
            partial = target.with_suffix(target.suffix + ".part")
            log.info("embedding_model_download", file=name)
            async with client.stream("GET", url, follow_redirects=True, timeout=120.0) as response:
                response.raise_for_status()
                with partial.open("wb") as handle:
                    async for chunk in response.aiter_bytes(1 << 20):
                        handle.write(chunk)
            actual = await anyio.to_thread.run_sync(sha256_of, partial)
            if actual != expected:
                partial.unlink(missing_ok=True)
                self._status = "erreur"
                raise RuntimeError(f"empreinte inattendue pour {name}")
            partial.replace(target)

    async def ensure(self, client: httpx.AsyncClient | None = None) -> None:
        if self._ready.is_set():
            return
        async with self._load_lock:
            if self._ready.is_set():
                return
            if not self.files_present():
                if client is None:
                    raise RuntimeError("modèle d'embeddings absent")
                await self.download(client)
            await anyio.to_thread.run_sync(self._load)
            self._status = "prêt"
            self._ready.set()

    def _load(self) -> None:
        import onnxruntime as ort  # noqa: PLC0415
        from tokenizers import Tokenizer  # noqa: PLC0415

        tokenizer = Tokenizer.from_file(str(self.folder / "tokenizer.json"))
        tokenizer.enable_truncation(max_length=256)
        tokenizer.enable_padding(pad_id=1, pad_token="<pad>")  # noqa: S106
        options = ort.SessionOptions()
        options.intra_op_num_threads = self._threads
        options.inter_op_num_threads = 1
        self._session = ort.InferenceSession(
            str(self.folder / "model_quantized.onnx"), options, providers=["CPUExecutionProvider"]
        )
        self._tokenizer = tokenizer

    def _run(self, texts: list[str]) -> Vectors:
        with self._run_lock:
            encodings = self._tokenizer.encode_batch(texts)
            ids = np.array([e.ids for e in encodings], dtype=np.int64)
            mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)
            feeds = {"input_ids": ids, "attention_mask": mask, "token_type_ids": np.zeros_like(ids)}
            hidden = self._session.run(None, feeds)[0]
        weights = mask[..., None].astype(np.float32)
        pooled = (hidden * weights).sum(axis=1) / np.maximum(weights.sum(axis=1), 1e-9)
        return _normalize(pooled.astype(np.float32))

    async def embed(self, texts: list[str], kind: Kind) -> Vectors:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        await self.ensure()
        prefixed = [f"{kind}: {text}" for text in texts]
        parts = [
            await anyio.to_thread.run_sync(self._run, prefixed[i : i + 16])
            for i in range(0, len(prefixed), 16)
        ]
        return np.concatenate(parts, axis=0)


_WORD = re.compile(r"\w+", re.UNICODE)


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


class HashEmbedder:
    """Embeddings déterministes par hachage de mots (tests, ou en attendant le vrai modèle)."""

    model_id = "hash"

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim

    @property
    def status(self) -> str:
        return "prêt"

    async def embed(self, texts: list[str], kind: Kind) -> Vectors:
        del kind
        rows = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in _WORD.findall(_fold(text)):
                if len(word) < 3:
                    continue
                digest = hashlib.blake2b(word.encode(), digest_size=8).digest()
                bucket = int.from_bytes(digest[:4], "little") % self.dim
                sign = 1.0 if digest[4] % 2 else -1.0
                rows[row, bucket] += sign
        return _normalize(rows)
