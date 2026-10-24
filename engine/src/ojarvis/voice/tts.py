"""Synthèse vocale en flux : Cartesia Sonic (en ligne) et Piper (local, repli hors ligne).

Chaque moteur reçoit les phrases au fil de l'eau et rend l'audio au fil de l'eau :
Jarvis commence à parler pendant que le modèle écrit encore la suite.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import time
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import anyio.to_thread
import numpy as np

from ojarvis.core.downloads import PinnedFile
from ojarvis.core.logs import get_logger
from ojarvis.voice.audio import OUTPUT_RATE, resample

log = get_logger(__name__)

CARTESIA_URL = "wss://api.cartesia.ai/tts/websocket"
CARTESIA_VERSION = "2026-08-14"
CARTESIA_MODEL = "sonic-3.6"
#: « Étienne » : voix masculine française, posée et précise.
DEFAULT_CARTESIA_VOICE = "c6ccfe32-6bee-484a-a8a2-7a51bee93f99"

PIPER_REVISION = "c10ece1aade47bb51c153c893d14e5bf8e5b7117"
PIPER_BASE = (
    f"https://huggingface.co/rhasspy/piper-voices/resolve/{PIPER_REVISION}/fr/fr_FR/tom/medium"
)
PIPER_VOICE = "fr_FR-tom-medium"
PIPER_FILES: dict[str, PinnedFile] = {
    f"{PIPER_VOICE}.onnx": PinnedFile(
        f"{PIPER_BASE}/{PIPER_VOICE}.onnx",
        "bf65074ccdeeeeaa832e75edb1c0a513c01c9a972bdf085ff8a6e71ea234fd41",
        63_511_038,
    ),
    f"{PIPER_VOICE}.onnx.json": PinnedFile(
        f"{PIPER_BASE}/{PIPER_VOICE}.onnx.json",
        "2f7f885ad5a0aad802e3cc24e4f57239febdcb142b4876de5d238094674361cc",
        4_959,
    ),
}


@dataclass(frozen=True)
class AudioChunk:
    pcm: bytes  # PCM 16 bits mono, petit-boutiste
    rate: int


class TTSError(Exception):
    """Le moteur de synthèse a échoué ; `spoken` dit si du son est déjà sorti."""

    def __init__(self, message: str, *, spoken: bool = False) -> None:
        super().__init__(message)
        self.spoken = spoken


class Synthesizer(Protocol):
    name: str

    @property
    def available(self) -> bool: ...

    async def warm_up(self) -> None: ...

    def stream(self, sentences: AsyncIterator[str]) -> AsyncGenerator[AudioChunk]: ...

    async def close(self) -> None: ...


# --------------------------------------------------------------------------- Cartesia


class CartesiaTTS:
    """WebSocket gardée ouverte entre les tours ; une « context_id » par réponse."""

    name = "cartesia"

    def __init__(
        self,
        api_key: Callable[[], str | None],
        *,
        voice: Callable[[], str] = lambda: DEFAULT_CARTESIA_VOICE,
        connect: Callable[..., Any] | None = None,
        connect_timeout_s: float = 4.0,
    ) -> None:
        self._api_key = api_key
        self._voice = voice
        self._connect = connect
        self._connect_timeout_s = connect_timeout_s
        self._ws: Any = None
        self._lock = asyncio.Lock()

    @property
    def available(self) -> bool:
        return bool(self._api_key())

    async def _connection(self) -> Any:
        async with self._lock:
            if self._ws is not None and getattr(self._ws, "close_code", None) is None:
                return self._ws
            key = self._api_key()
            if not key:
                raise TTSError("clé Cartesia absente")
            connect = self._connect
            if connect is None:
                import websockets  # noqa: PLC0415

                connect = websockets.connect
            self._ws = await asyncio.wait_for(
                connect(
                    f"{CARTESIA_URL}?cartesia_version={CARTESIA_VERSION}",
                    additional_headers={"X-API-Key": key, "Cartesia-Version": CARTESIA_VERSION},
                    max_size=2**22,
                ),
                timeout=self._connect_timeout_s,
            )
            return self._ws

    async def warm_up(self) -> None:
        """Ouvre la connexion à l'avance (au mot de réveil) : 250 ms de gagnées sur le tour."""
        with contextlib.suppress(Exception):
            await self._connection()

    async def close(self) -> None:
        ws, self._ws = self._ws, None
        if ws is not None:
            with contextlib.suppress(Exception):
                await ws.close()

    def _request(self, context_id: str) -> dict[str, Any]:
        return {
            "model_id": CARTESIA_MODEL,
            "voice": {"mode": "id", "id": self._voice()},
            "language": "fr",
            "context_id": context_id,
            "output_format": {
                "container": "raw",
                "encoding": "pcm_s16le",
                "sample_rate": OUTPUT_RATE,
            },
        }

    @staticmethod
    async def _send_all(ws: Any, base: dict[str, Any], sentences: AsyncIterator[str]) -> None:
        first = True
        async for sentence in sentences:
            # Le premier morceau part sans attendre : c'est lui qui fixe la latence.
            delay = 0 if first else 400
            first = False
            message = {**base, "transcript": sentence + " ", "continue": True}
            await ws.send(json.dumps({**message, "max_buffer_delay_ms": delay}))
        await ws.send(json.dumps({**base, "transcript": "", "continue": False}))

    @staticmethod
    async def _receive(
        ws: Any, context_id: str, sender: asyncio.Task[None], spoken: list[bool]
    ) -> AsyncGenerator[AudioChunk]:
        while True:
            if sender.done() and sender.exception() is not None:
                raise TTSError("envoi vers Cartesia interrompu", spoken=bool(spoken))
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=8.0)
            except TimeoutError as exc:
                if not sender.done():
                    continue  # le modèle écrit encore : rien à dire pour l'instant
                raise TTSError("Cartesia ne répond plus", spoken=bool(spoken)) from exc
            message = json.loads(raw)
            if message.get("context_id") not in (None, context_id):
                continue
            kind = message.get("type")
            if kind == "chunk" and message.get("data"):
                spoken.append(True)
                yield AudioChunk(base64.b64decode(message["data"]), OUTPUT_RATE)
            elif kind == "done":
                return
            elif kind == "error":
                detail = message.get("title") or message.get("error_code") or "erreur"
                raise TTSError(f"Cartesia : {detail}", spoken=bool(spoken))

    async def stream(self, sentences: AsyncIterator[str]) -> AsyncGenerator[AudioChunk]:
        try:
            ws = await self._connection()
        except TTSError:
            raise
        except Exception as exc:
            raise TTSError(f"connexion Cartesia impossible : {type(exc).__name__}") from exc
        context_id = uuid.uuid4().hex
        spoken: list[bool] = []
        sender = asyncio.create_task(self._send_all(ws, self._request(context_id), sentences))
        finished = False
        try:
            async with contextlib.aclosing(self._receive(ws, context_id, sender, spoken)) as audio:
                async for chunk in audio:
                    yield chunk
            finished = True
        except TTSError:
            await self.close()
            raise
        except Exception as exc:
            await self.close()
            raise TTSError(f"Cartesia : {type(exc).__name__}", spoken=bool(spoken)) from exc
        finally:
            if not sender.done():
                sender.cancel()
            with contextlib.suppress(BaseException):
                await sender
            if not finished and self._ws is not None:
                with contextlib.suppress(Exception):
                    await self._ws.send(json.dumps({"context_id": context_id, "cancel": True}))


# --------------------------------------------------------------------------- Piper


class PiperTTS:
    """Voix locale (fr_FR « tom »), phrase par phrase, dans un fil séparé."""

    name = "piper"

    def __init__(self, folder: Path, *, voice: str = PIPER_VOICE) -> None:
        self._model_path = folder / f"{voice}.onnx"
        self._voice: Any = None
        self._lock = asyncio.Lock()

    @property
    def available(self) -> bool:
        return self._model_path.is_file()

    def _load(self) -> Any:
        if self._voice is None:
            from piper import PiperVoice  # noqa: PLC0415

            self._voice = PiperVoice.load(self._model_path)
        return self._voice

    async def warm_up(self) -> None:
        async with self._lock:
            await anyio.to_thread.run_sync(self._load)

    async def close(self) -> None:
        return None

    def _synthesize(self, text: str) -> tuple[bytes, int]:
        voice = self._load()
        chunks = list(voice.synthesize(text))
        if not chunks:
            return b"", OUTPUT_RATE
        audio = np.concatenate([c.audio_int16_array for c in chunks])
        rate = int(chunks[0].sample_rate)
        return resample(audio, rate, OUTPUT_RATE).tobytes(), OUTPUT_RATE

    async def stream(self, sentences: AsyncIterator[str]) -> AsyncGenerator[AudioChunk]:
        async for sentence in sentences:
            async with self._lock:
                pcm, rate = await anyio.to_thread.run_sync(self._synthesize, sentence)
            if pcm:
                yield AudioChunk(pcm, rate)


# --------------------------------------------------------------------------- repli


@dataclass
class _Replay:
    """Garde les phrases déjà lues pour pouvoir les redonner au moteur de secours."""

    source: AsyncIterator[str]
    seen: list[str] = field(default_factory=list)
    exhausted: bool = False

    async def live(self) -> AsyncIterator[str]:
        async for sentence in self.source:
            self.seen.append(sentence)
            yield sentence
        self.exhausted = True

    async def from_index(self, index: int) -> AsyncIterator[str]:
        for sentence in self.seen[index:]:
            yield sentence
        if not self.exhausted:
            async for sentence in self.live():
                yield sentence


class FallbackTTS:
    """Cartesia d'abord ; Piper prend le relais si Cartesia échoue, même en cours de réponse.

    Après un échec, Cartesia est mis de côté pendant `cooldown_s` : les réponses suivantes
    partent directement sur Piper, sans attendre un nouvel échec.
    """

    name = "auto"

    def __init__(
        self,
        primary: Synthesizer,
        secondary: Synthesizer,
        *,
        cooldown_s: float = 60.0,
        on_fallback: Callable[[str], None] | None = None,
        prefer_secondary: Callable[[], bool] = lambda: False,
    ) -> None:
        self.primary = primary
        self.secondary = secondary
        self._cooldown_s = cooldown_s
        self._degraded_until = 0.0
        self._on_fallback = on_fallback
        self._prefer_secondary = prefer_secondary
        self.last_engine: str | None = None

    @property
    def available(self) -> bool:
        return self.primary.available or self.secondary.available

    def _use_primary(self) -> bool:
        return (
            not self._prefer_secondary()
            and self.primary.available
            and time.monotonic() >= self._degraded_until
        )

    async def warm_up(self) -> None:
        if self._use_primary():
            await self.primary.warm_up()
        else:
            await self.secondary.warm_up()

    async def close(self) -> None:
        await self.primary.close()
        await self.secondary.close()

    async def stream(self, sentences: AsyncIterator[str]) -> AsyncGenerator[AudioChunk]:
        replay = _Replay(sentences)
        start_index = 0
        if self._use_primary():
            self.last_engine = self.primary.name
            sent = 0
            try:
                async with contextlib.aclosing(self.primary.stream(replay.live())) as chunks:
                    async for chunk in chunks:
                        yield chunk
                return
            except TTSError as error:
                self._degraded_until = time.monotonic() + self._cooldown_s
                log.warning("tts_fallback", engine=self.primary.name, error=str(error))
                if self._on_fallback is not None:
                    self._on_fallback(str(error))
                # Déjà parlé : on reprend à la phrase en cours ; sinon tout depuis le début.
                sent = max(len(replay.seen) - 1, 0) if error.spoken else 0
            start_index = sent
        self.last_engine = self.secondary.name
        async with contextlib.aclosing(
            self.secondary.stream(replay.from_index(start_index))
        ) as chunks:
            async for chunk in chunks:
                yield chunk
