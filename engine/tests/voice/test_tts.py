"""Synthèse vocale : protocole Cartesia (WebSocket simulée) et repli sur Piper."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from ojarvis.voice.tts import AudioChunk, CartesiaTTS, FallbackTTS, TTSError


async def sentences(*items: str) -> AsyncIterator[str]:
    for item in items:
        await asyncio.sleep(0)
        yield item


async def collect(stream: AsyncIterator[AudioChunk]) -> list[bytes]:
    return [chunk.pcm async for chunk in stream]


# ---------------------------------------------------------------- repli


@dataclass
class ScriptedSynth:
    name: str
    fail_at: int | None = None  # échoue en recevant la phrase n° fail_at
    spoken_before_failure: bool = False
    received: list[str] = field(default_factory=list)
    available: bool = True

    async def warm_up(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def stream(self, items: AsyncIterator[str]) -> AsyncIterator[AudioChunk]:
        async for sentence in items:
            if self.fail_at is not None and len(self.received) == self.fail_at:
                self.received.append(sentence)
                raise TTSError("panne", spoken=self.spoken_before_failure)
            self.received.append(sentence)
            yield AudioChunk(f"{self.name}:{sentence}".encode(), 24_000)


async def test_primary_failing_before_any_sound_hands_everything_to_piper() -> None:
    primary = ScriptedSynth("cartesia", fail_at=0)
    secondary = ScriptedSynth("piper")
    fallbacks: list[str] = []
    tts = FallbackTTS(primary, secondary, on_fallback=fallbacks.append)
    out = await collect(tts.stream(sentences("Un.", "Deux.")))
    assert out == [b"piper:Un.", b"piper:Deux."]
    assert fallbacks == ["panne"]
    assert tts.last_engine == "piper"
    # Pendant la mise à l'écart, Cartesia n'est même plus essayé.
    await collect(tts.stream(sentences("Trois.")))
    assert primary.received == ["Un."]


async def test_primary_failing_mid_answer_resumes_on_the_current_sentence() -> None:
    primary = ScriptedSynth("cartesia", fail_at=1, spoken_before_failure=True)
    secondary = ScriptedSynth("piper")
    tts = FallbackTTS(primary, secondary)
    out = await collect(tts.stream(sentences("Un.", "Deux.", "Trois.")))
    assert out == [b"cartesia:Un.", b"piper:Deux.", b"piper:Trois."]


async def test_piper_can_be_preferred() -> None:
    primary = ScriptedSynth("cartesia")
    tts = FallbackTTS(primary, ScriptedSynth("piper"), prefer_secondary=lambda: True)
    assert await collect(tts.stream(sentences("Un."))) == [b"piper:Un."]
    assert primary.received == []


async def test_without_key_cartesia_is_skipped() -> None:
    primary = ScriptedSynth("cartesia", available=False)
    tts = FallbackTTS(primary, ScriptedSynth("piper"))
    assert await collect(tts.stream(sentences("Un."))) == [b"piper:Un."]


# ---------------------------------------------------------------- Cartesia


class FakeSocket:
    """Répond comme Cartesia : un morceau d'audio par phrase, puis `done` à la fin."""

    def __init__(self, *, error: bool = False) -> None:
        self.sent: list[dict[str, Any]] = []
        self.incoming: asyncio.Queue[str] = asyncio.Queue()
        self.close_code: int | None = None
        self._error = error

    async def send(self, raw: str) -> None:
        message = json.loads(raw)
        self.sent.append(message)
        context = message.get("context_id")
        if message.get("cancel"):
            return
        if self._error:
            await self.incoming.put(
                json.dumps({"type": "error", "context_id": context, "title": "quota"})
            )
            return
        if message.get("transcript"):
            data = base64.b64encode(message["transcript"].encode()).decode()
            await self.incoming.put(
                json.dumps({"type": "chunk", "context_id": context, "data": data})
            )
        if message.get("continue") is False:
            await self.incoming.put(json.dumps({"type": "done", "context_id": context}))

    async def recv(self) -> str:
        return await self.incoming.get()

    async def close(self) -> None:
        self.close_code = 1000


@dataclass
class Connector:
    socket: FakeSocket
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def __call__(self, url: str, **kwargs: Any) -> FakeSocket:
        self.calls.append({"url": url, **kwargs})
        return self.socket


async def test_cartesia_streams_sentences_and_audio() -> None:
    connector = Connector(FakeSocket())
    tts = CartesiaTTS(lambda: "cle-de-test", connect=connector)
    out = await collect(tts.stream(sentences("Bonjour.", "Ça va ?")))
    assert out == [b"Bonjour. ", "Ça va ? ".encode()]
    sent = connector.socket.sent
    assert [m["transcript"] for m in sent] == ["Bonjour. ", "Ça va ? ", ""]
    assert [m["continue"] for m in sent] == [True, True, False]
    assert sent[0]["max_buffer_delay_ms"] == 0  # la première phrase part sans attendre
    assert len({m["context_id"] for m in sent}) == 1
    assert sent[0]["language"] == "fr"
    assert sent[0]["output_format"]["encoding"] == "pcm_s16le"
    call = connector.calls[0]
    assert call["additional_headers"]["X-API-Key"] == "cle-de-test"
    assert "cle-de-test" not in call["url"]  # la clé ne passe jamais dans l'URL
    # La connexion est réutilisée au tour suivant.
    await collect(tts.stream(sentences("Encore.")))
    assert len(connector.calls) == 1


async def test_cartesia_error_raises_and_reconnects_next_time() -> None:
    connector = Connector(FakeSocket(error=True))
    tts = CartesiaTTS(lambda: "cle", connect=connector)
    with pytest.raises(TTSError, match="quota"):
        await collect(tts.stream(sentences("Bonjour.")))
    connector.socket = FakeSocket()
    assert await collect(tts.stream(sentences("Re."))) == [b"Re. "]
    assert len(connector.calls) == 2


async def test_cartesia_cancels_the_context_when_interrupted() -> None:
    socket = FakeSocket()
    tts = CartesiaTTS(lambda: "cle", connect=Connector(socket))
    stream = tts.stream(sentences("Un.", "Deux.", "Trois."))
    async with contextlib.aclosing(stream) as chunks:
        async for _ in chunks:
            break  # l'utilisateur coupe Jarvis
    assert socket.sent[-1].get("cancel") is True


async def test_cartesia_without_key_fails_fast() -> None:
    tts = CartesiaTTS(lambda: None, connect=Connector(FakeSocket()))
    assert not tts.available
    with pytest.raises(TTSError):
        await collect(tts.stream(sentences("Bonjour.")))
