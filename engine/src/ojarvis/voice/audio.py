"""Audio du pipeline vocal : trames de 80 ms en 16 kHz mono 16 bits, entrées et sorties.

Le micro et les fichiers produisent des trames horodatées (`time.monotonic()`), ce qui
permet de mesurer la latence réelle entre la fin d'une phrase et le début de la réponse.
"""

from __future__ import annotations

import asyncio
import contextlib
import math
import threading
import time
import wave
from collections import deque
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from dataclasses import dataclass, field
from math import gcd
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt

from ojarvis.core.logs import get_logger

log = get_logger(__name__)

RATE = 16_000
#: 80 ms : la taille de trame attendue par openWakeWord.
FRAME_SAMPLES = 1280
FRAME_S = FRAME_SAMPLES / RATE
#: Fréquence de la synthèse vocale jouée (Cartesia la produit directement).
OUTPUT_RATE = 24_000

Pcm = npt.NDArray[np.int16]


@dataclass(frozen=True)
class Frame:
    pcm: Pcm
    #: Instant (horloge monotone) où la fin de la trame a été captée.
    at: float


def level(pcm: Pcm) -> float:
    """Niveau perçu entre 0 et 1 : RMS en dBFS, ramené de [-60 dB, 0 dB] vers [0, 1]."""
    if pcm.size == 0:
        return 0.0
    rms = math.sqrt(float(np.mean(np.square(pcm.astype(np.float32))))) / 32768.0
    if rms <= 1e-6:
        return 0.0
    return min(1.0, max(0.0, (20.0 * math.log10(rms) + 60.0) / 60.0))


def resample(audio: Pcm, rate_in: int, rate_out: int) -> Pcm:
    if rate_in == rate_out or audio.size == 0:
        return audio
    from scipy.signal import resample_poly  # noqa: PLC0415

    factor = gcd(rate_in, rate_out)
    out = resample_poly(audio.astype(np.float32), rate_out // factor, rate_in // factor)
    result: Pcm = np.clip(out, -32768, 32767).astype(np.int16)
    return result


def read_wav(path: Path) -> Pcm:
    """Lit un WAV 16 bits (mono ou stéréo, toute fréquence) et le ramène en 16 kHz mono."""
    with wave.open(str(path), "rb") as handle:
        if handle.getsampwidth() != 2:
            raise ValueError("WAV 16 bits attendu")
        channels = handle.getnchannels()
        rate = handle.getframerate()
        audio = np.frombuffer(handle.readframes(handle.getnframes()), dtype=np.int16)
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1).astype(np.int16)
    return resample(audio, rate, RATE)


def write_wav(path: Path, audio: Pcm, rate: int = RATE) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(audio.astype(np.int16).tobytes())


# --------------------------------------------------------------------------- entrées


class AudioSource(Protocol):
    def frames(self) -> AsyncIterator[Frame]: ...

    async def close(self) -> None: ...


class VirtualClock:
    """Horloge des tests : elle n'avance que lorsqu'une trame est livrée."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FileSource:
    """Rejoue un fichier comme un micro : en temps réel, puis du silence jusqu'à la fermeture.

    Avec une `VirtualClock`, les trames arrivent aussi vite que possible et l'horloge
    avance de 80 ms à chaque trame : les tests du pipeline ne dorment jamais.
    """

    def __init__(
        self,
        audio: Pcm,
        *,
        realtime: bool = True,
        speed: float = 1.0,
        tail_s: float | None = None,
        clock: VirtualClock | None = None,
    ) -> None:
        self._audio = audio
        self._realtime = realtime and clock is None
        self._speed = speed
        self._tail_s = tail_s
        self._clock = clock
        self._closed = asyncio.Event()
        #: Instant où la dernière trame du fichier a été livrée.
        self.finished_at: float | None = None

    def _now(self) -> float:
        return self._clock() if self._clock is not None else time.monotonic()

    @classmethod
    def from_wav(cls, path: Path, **kwargs: Any) -> FileSource:
        return cls(read_wav(path), **kwargs)

    async def close(self) -> None:
        self._closed.set()

    async def frames(self) -> AsyncGenerator[Frame]:
        rng = np.random.default_rng(7)
        start = time.monotonic()
        index = 0
        total = len(self._audio)
        tail_frames = None if self._tail_s is None else int(self._tail_s / FRAME_S)
        while not self._closed.is_set():
            offset = index * FRAME_SAMPLES
            if offset < total:
                pcm = self._audio[offset : offset + FRAME_SAMPLES]
                if len(pcm) < FRAME_SAMPLES:
                    pcm = np.concatenate([pcm, np.zeros(FRAME_SAMPLES - len(pcm), np.int16)])
            else:
                if self.finished_at is None:
                    self.finished_at = self._now()
                done = (offset - total) // FRAME_SAMPLES
                if tail_frames is not None and done >= tail_frames:
                    return
                pcm = rng.normal(0, 10, FRAME_SAMPLES).astype(np.int16)
            index += 1
            if self._clock is not None:
                self._clock.advance(FRAME_S)
                for _ in range(3):  # laisse les tâches du pipeline avancer entre deux trames
                    await asyncio.sleep(0)
            elif self._realtime:
                due = start + index * FRAME_S / self._speed
                delay = due - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
            else:
                await asyncio.sleep(0)
            yield Frame(pcm, self._now())


class MicrophoneSilentError(RuntimeError):
    """Le micro n'envoie plus rien : périphérique débranché ou flux audio bloqué."""


async def close_stream(stream: Any, *, timeout_s: float = 2.0) -> None:
    """Ferme un flux PortAudio hors de la boucle : un pilote bloqué ne fige pas le moteur."""

    def close() -> None:
        with contextlib.suppress(Exception):
            stream.stop()
        with contextlib.suppress(Exception):
            stream.close()

    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(asyncio.to_thread(close), timeout_s)


class MicrophoneSource:
    """Micro via PortAudio. Le flux est ouvert en 16 kHz ; sinon à la fréquence du périphérique."""

    def __init__(
        self, device: str | int | None = None, *, max_queue: int = 64, silent_after_s: float = 3.0
    ) -> None:
        self._device = device
        self._queue: asyncio.Queue[Frame | None] = asyncio.Queue(max_queue)
        self._stream: Any = None
        self._dropped = 0
        self._silent_after_s = silent_after_s

    async def close(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            await close_stream(stream)
        with contextlib.suppress(asyncio.QueueFull):
            self._queue.put_nowait(None)

    def _open(self, loop: asyncio.AbstractEventLoop) -> None:
        import sounddevice as sd  # noqa: PLC0415

        def push(frame: Frame) -> None:
            if self._queue.full():
                self._dropped += 1
                with contextlib.suppress(asyncio.QueueEmpty):
                    self._queue.get_nowait()
            self._queue.put_nowait(frame)

        try:
            rate = RATE
            sd.check_input_settings(device=self._device, channels=1, dtype="int16", samplerate=rate)
        except Exception:
            info = sd.query_devices(self._device, "input")
            rate = int(info["default_samplerate"])
            # Import lent la première fois : fait ici, pas dans le rappel audio.
            from scipy.signal import resample_poly  # noqa: F401, PLC0415
        block = int(rate * FRAME_S)

        def callback(indata: Any, frames: int, _time: Any, status: Any) -> None:
            del frames
            if status:
                log.debug("microphone_status", status=str(status))
            pcm = np.array(indata[:, 0], dtype=np.int16)
            if rate != RATE:
                pcm = resample(pcm, rate, RATE)[:FRAME_SAMPLES]
            loop.call_soon_threadsafe(push, Frame(pcm, time.monotonic()))

        self._stream = sd.InputStream(
            device=self._device,
            channels=1,
            dtype="int16",
            samplerate=rate,
            blocksize=block,
            latency="low",
            callback=callback,
        )
        self._stream.start()

    async def frames(self) -> AsyncGenerator[Frame]:
        self._open(asyncio.get_running_loop())
        # La première trame peut tarder (ouverture du périphérique) : délai plus large.
        wait = self._silent_after_s * 3
        try:
            while True:
                try:
                    frame = await asyncio.wait_for(self._queue.get(), wait)
                except TimeoutError as exc:
                    raise MicrophoneSilentError("le micro ne transmet plus rien") from exc
                wait = self._silent_after_s
                if frame is None:
                    return
                yield frame
        finally:
            await self.close()


# --------------------------------------------------------------------------- sorties


class AudioSink(Protocol):
    #: Niveau de ce qui est joué en ce moment (0 à 1), pour la sphère.
    level: float
    #: Instant estimé où le premier son de la réponse en cours sort du haut-parleur.
    first_audio_at: float | None

    def begin(self) -> None: ...

    async def play(self, pcm: bytes, rate: int) -> None: ...

    async def drain(self) -> None: ...

    def stop(self) -> None: ...

    async def close(self) -> None: ...


@dataclass
class _Playback:
    buffer: deque[Pcm] = field(default_factory=deque)
    offset: int = 0
    queued: int = 0
    played: int = 0


class SpeakerSink:
    """Haut-parleur via PortAudio, ouvert à la demande et refermé après un silence."""

    def __init__(self, device: str | int | None = None, *, idle_close_s: float = 3.0) -> None:
        self._device = device
        self._idle_close_s = idle_close_s
        self._lock = threading.Lock()
        self._state = _Playback()
        self._stream: Any = None
        self._rate = OUTPUT_RATE
        self._latency_s = 0.0
        self._idle_task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._started = False
        self._drained = asyncio.Event()
        self.level = 0.0
        self.first_audio_at: float | None = None

    def begin(self) -> None:
        """Nouvelle réponse : la prochaine trame non vide fixe `first_audio_at`."""
        self.first_audio_at = None
        self._started = False

    def _callback(self, outdata: Any, frames: int, timing: Any, status: Any) -> None:
        del status
        out = np.zeros(frames, dtype=np.int16)
        filled = 0
        with self._lock:
            state = self._state
            while filled < frames and state.buffer:
                head = state.buffer[0]
                take = min(frames - filled, len(head) - state.offset)
                out[filled : filled + take] = head[state.offset : state.offset + take]
                filled += take
                state.offset += take
                if state.offset >= len(head):
                    state.buffer.popleft()
                    state.offset = 0
            state.played += filled
            emptied = filled > 0 and not state.buffer
        if emptied and self._loop is not None:
            self._loop.call_soon_threadsafe(self._drained.set)
        if filled and not self._started:
            self._started = True
            delay = 0.0
            with contextlib.suppress(Exception):
                delay = max(0.0, float(timing.outputBufferDacTime - timing.currentTime))
            self.first_audio_at = time.monotonic() + (delay or self._latency_s)
        self.level = level(out[:filled]) if filled else 0.0
        outdata[:, 0] = out

    def _ensure_stream(self) -> None:
        if self._stream is not None:
            return
        import sounddevice as sd  # noqa: PLC0415

        rate = OUTPUT_RATE
        try:
            sd.check_output_settings(
                device=self._device, channels=1, dtype="int16", samplerate=rate
            )
        except Exception:
            info = sd.query_devices(self._device, "output")
            rate = int(info["default_samplerate"])
        self._rate = rate
        self._stream = sd.OutputStream(
            device=self._device,
            channels=1,
            dtype="int16",
            samplerate=rate,
            latency="low",
            callback=self._callback,
        )
        self._latency_s = float(self._stream.latency or 0.0)
        self._stream.start()

    async def play(self, pcm: bytes, rate: int) -> None:
        self._loop = asyncio.get_running_loop()
        if self._idle_task is not None:
            self._idle_task.cancel()
            self._idle_task = None
        self._ensure_stream()
        audio = resample(np.frombuffer(pcm, dtype=np.int16), rate, self._rate)
        self._drained.clear()
        with self._lock:
            self._state.buffer.append(audio)
            self._state.queued += len(audio)

    def pending_s(self) -> float:
        with self._lock:
            return (self._state.queued - self._state.played) / self._rate

    async def drain(self) -> None:
        """Attend la fin de la lecture (plus la latence de sortie), puis planifie la fermeture."""
        if self.pending_s() > 0:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._drained.wait(), timeout=self.pending_s() + 1.0)
        await asyncio.sleep(self._latency_s)
        self.level = 0.0
        self._schedule_close()

    def stop(self) -> None:
        with self._lock:
            self._state = _Playback()
        self._drained.set()
        self.level = 0.0
        self._schedule_close()

    def _schedule_close(self) -> None:
        if self._loop is None or self._stream is None:
            return

        async def close_later() -> None:
            await asyncio.sleep(self._idle_close_s)
            await self.close()

        if self._idle_task is None or self._idle_task.done():
            self._idle_task = self._loop.create_task(close_later())

    async def close(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            await close_stream(stream)


class MemorySink:
    """Sortie de test : garde l'audio reçu et simule la durée de lecture."""

    def __init__(
        self, *, realtime: bool = True, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._realtime = realtime
        self._clock = clock
        self.level = 0.0
        self.first_audio_at: float | None = None
        self.chunks: list[tuple[bytes, int]] = []
        self.stopped = 0
        self._ends_at = 0.0
        self.on_play: Callable[[], None] | None = None

    def begin(self) -> None:
        self.first_audio_at = None

    async def play(self, pcm: bytes, rate: int) -> None:
        now = self._clock()
        if self.first_audio_at is None:
            self.first_audio_at = now
            self._ends_at = now
        self.chunks.append((pcm, rate))
        self._ends_at = max(self._ends_at, now) + len(pcm) / 2 / rate
        self.level = level(np.frombuffer(pcm, dtype=np.int16))
        if self.on_play is not None:
            self.on_play()

    async def drain(self) -> None:
        if isinstance(self._clock, VirtualClock):
            # Horloge virtuelle : le temps n'avance qu'avec les trames, on rend la main.
            while self._clock() < self._ends_at:  # noqa: ASYNC110
                await asyncio.sleep(0)
        elif self._realtime:
            delay = self._ends_at - self._clock()
            if delay > 0:
                await asyncio.sleep(delay)
        self.level = 0.0

    def stop(self) -> None:
        self.stopped += 1
        self._ends_at = self._clock()
        self.level = 0.0

    async def close(self) -> None:
        return None

    def audio_s(self) -> float:
        return sum(len(pcm) / 2 / rate for pcm, rate in self.chunks)
