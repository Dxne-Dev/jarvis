"""Transcription en ligne (Cartesia Ink-2) avec une WebSocket simulée."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pytest

from ojarvis.voice.audio import FRAME_SAMPLES
from ojarvis.voice.stt import CartesiaSTT, SttError


class FakeSttSocket:
    """Comme Cartesia : à chaque « finalize », le texte de l'audio reçu depuis, puis un accusé."""

    def __init__(self, *, mode: str = "ok") -> None:
        self.mode = mode
        self.audio: list[int] = []
        self.texts: list[str] = []
        self.incoming: asyncio.Queue[str] = asyncio.Queue()
        self.closed = False
        self._pending = 0

    async def send(self, message: bytes | str) -> None:
        if isinstance(message, bytes):
            self.audio.append(len(message))
            self._pending += len(message)
            return
        self.texts.append(message)
        if message != "finalize" or self.mode == "muet":
            return
        if self.mode == "erreur":
            await self.incoming.put(json.dumps({"type": "error", "title": "quota dépassé"}))
            return
        text = f"{self._pending // 2} échantillons. "
        self._pending = 0
        await self.incoming.put(json.dumps({"type": "transcript", "is_final": False, "text": "…"}))
        await self.incoming.put(json.dumps({"type": "transcript", "is_final": True, "text": text}))
        await self.incoming.put(json.dumps({"type": "flush_done"}))

    async def recv(self) -> str:
        return await self.incoming.get()

    async def close(self) -> None:
        self.closed = True


@dataclass
class Connector:
    socket: FakeSttSocket
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def __call__(self, url: str, **kwargs: Any) -> FakeSttSocket:
        self.calls.append({"url": url, **kwargs})
        return self.socket


def frame(value: int = 1000) -> np.ndarray:
    return np.full(FRAME_SAMPLES, value, dtype=np.int16)


async def test_audio_streams_and_the_text_comes_back_at_the_end() -> None:
    connector = Connector(FakeSttSocket())
    stt = CartesiaSTT(lambda: "cle-de-test", connect=connector)
    stream = stt.open()
    for _ in range(3):
        stream.send(frame())
    transcript = await stream.finish()
    assert transcript.text == f"{3 * FRAME_SAMPLES} échantillons."
    assert transcript.audio_s == pytest.approx(0.24)
    assert transcript.reliable  # le modèle en ligne ne donne pas de note : on lui fait confiance
    call = connector.calls[0]
    assert "model=ink-2" in call["url"]
    assert "keyterm=Jarvis" in call["url"]
    assert "sample_rate=16000" in call["url"]
    assert call["additional_headers"] == {"X-API-Key": "cle-de-test"}
    assert "cle-de-test" not in call["url"]
    assert connector.socket.texts == ["finalize"]
    await asyncio.sleep(0.01)  # la connexion se ferme à côté, sans faire attendre le texte
    assert connector.socket.closed


async def test_text_asked_at_a_pause_is_ready_when_the_sentence_ends() -> None:
    socket = FakeSttSocket()
    stream = CartesiaSTT(lambda: "cle", connect=Connector(socket)).open()
    stream.send(frame())
    stream.flush()  # courte pause : on demande déjà le texte
    await asyncio.sleep(0.01)
    transcript = await stream.finish()  # rien de neuf depuis : pas de second « finalize »
    assert socket.texts == ["finalize"]
    assert transcript.text == f"{FRAME_SAMPLES} échantillons."


async def test_speech_that_resumes_after_a_pause_is_concatenated() -> None:
    socket = FakeSttSocket()
    stream = CartesiaSTT(lambda: "cle", connect=Connector(socket)).open()
    stream.send(frame())
    stream.flush()
    stream.send(frame())
    stream.send(frame())
    transcript = await stream.finish()
    assert socket.texts == ["finalize", "finalize"]
    assert transcript.text == f"{FRAME_SAMPLES} échantillons. {2 * FRAME_SAMPLES} échantillons."


async def test_an_error_from_cartesia_is_raised() -> None:
    stream = CartesiaSTT(lambda: "cle", connect=Connector(FakeSttSocket(mode="erreur"))).open()
    stream.send(frame())
    with pytest.raises(SttError):
        await stream.finish()


async def test_no_answer_in_time_is_an_error() -> None:
    socket = FakeSttSocket(mode="muet")
    stream = CartesiaSTT(lambda: "cle", connect=Connector(socket)).open()
    stream.send(frame())
    with pytest.raises(SttError, match="à temps"):
        await stream.finish(timeout_s=0.05)
    assert socket.closed


async def test_an_unreachable_service_is_an_error() -> None:
    async def refuse(url: str, **_: Any) -> None:
        raise OSError("réseau coupé")

    stream = CartesiaSTT(lambda: "cle", connect=refuse).open()
    stream.send(frame())
    with pytest.raises(SttError):
        await stream.finish()


async def test_without_key_the_service_is_not_available() -> None:
    assert not CartesiaSTT(lambda: None).available
    assert CartesiaSTT(lambda: "cle").available
