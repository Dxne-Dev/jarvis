"""Micro et haut-parleur, avec un faux module `sounddevice` (pas de vrai périphérique)."""

from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from ojarvis.voice.audio import (
    FRAME_SAMPLES,
    OUTPUT_RATE,
    FileSource,
    MicrophoneSilentError,
    MicrophoneSource,
    SpeakerSink,
    read_wav,
    write_wav,
)


class FakeStream:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.callback = kwargs["callback"]
        self.latency = 0.02
        self.started = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_sd(monkeypatch: pytest.MonkeyPatch) -> types.SimpleNamespace:
    created: list[FakeStream] = []
    state = types.SimpleNamespace(created=created, native_16k=True)

    def check(**_: Any) -> None:
        if not state.native_16k:
            raise ValueError("fréquence refusée")

    def stream(**kwargs: Any) -> FakeStream:
        created.append(FakeStream(**kwargs))
        return created[-1]

    module = types.ModuleType("sounddevice")
    module.check_input_settings = check  # type: ignore[attr-defined]
    module.check_output_settings = check  # type: ignore[attr-defined]
    module.query_devices = lambda *_a, **_k: {"default_samplerate": 48000.0}  # type: ignore[attr-defined]
    module.InputStream = stream  # type: ignore[attr-defined]
    module.OutputStream = stream  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sounddevice", module)
    return state


async def test_microphone_delivers_timestamped_frames(fake_sd: types.SimpleNamespace) -> None:
    mic = MicrophoneSource("Micro de test")
    frames = mic.frames()
    first = asyncio.ensure_future(anext(frames))
    await asyncio.sleep(0)
    stream = fake_sd.created[0]
    assert stream.kwargs["samplerate"] == 16_000
    assert stream.kwargs["device"] == "Micro de test"
    block = np.full((FRAME_SAMPLES, 1), 1000, dtype=np.int16)
    stream.callback(block, FRAME_SAMPLES, None, None)
    frame = await asyncio.wait_for(first, 1)
    assert frame.pcm.shape == (FRAME_SAMPLES,)
    assert int(frame.pcm[0]) == 1000
    await mic.close()
    assert stream.closed
    await frames.aclose()


async def test_microphone_resamples_when_16k_is_refused(fake_sd: types.SimpleNamespace) -> None:
    fake_sd.native_16k = False
    mic = MicrophoneSource(None)
    frames = mic.frames()
    first = asyncio.ensure_future(anext(frames))
    await asyncio.sleep(0)
    stream = fake_sd.created[0]
    assert stream.kwargs["samplerate"] == 48_000
    stream.callback(np.zeros((3840, 1), dtype=np.int16), 3840, None, None)
    frame = await asyncio.wait_for(first, 1)
    assert frame.pcm.shape == (FRAME_SAMPLES,)
    await mic.close()
    await frames.aclose()


async def test_speaker_plays_measures_and_stops(fake_sd: types.SimpleNamespace) -> None:
    sink = SpeakerSink("Haut-parleur de test", idle_close_s=0.01)
    sink.begin()
    tone = (8000 * np.sin(np.linspace(0, 200, OUTPUT_RATE // 10))).astype(np.int16)
    await sink.play(tone.tobytes(), OUTPUT_RATE)
    stream = fake_sd.created[0]
    assert sink.pending_s() == pytest.approx(0.1)

    timing = types.SimpleNamespace(outputBufferDacTime=1.05, currentTime=1.0)
    out = np.zeros((1200, 1), dtype=np.int16)
    stream.callback(out, 1200, timing, None)
    assert sink.first_audio_at is not None
    assert sink.level > 0.5
    assert np.array_equal(out[:, 0], tone[:1200])

    stream.callback(np.zeros((1200, 1), dtype=np.int16), 1200, timing, None)
    await asyncio.wait_for(sink.drain(), 1)
    assert sink.pending_s() == 0

    await sink.play(tone.tobytes(), OUTPUT_RATE)
    sink.stop()
    assert sink.pending_s() == 0
    assert sink.level == 0.0
    await asyncio.sleep(0.05)  # fermeture après le délai d'inactivité
    assert stream.closed


def test_wav_roundtrip_and_conversion(tmp_path: Path) -> None:
    stereo = np.zeros((48_000, 2), dtype=np.int16)
    stereo[:, 0] = 1000
    path = tmp_path / "stereo.wav"
    import wave  # noqa: PLC0415

    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(48_000)
        handle.writeframes(stereo.tobytes())
    mono = read_wav(path)
    assert len(mono) == 16_000
    out = tmp_path / "mono.wav"
    write_wav(out, mono)
    assert len(read_wav(out)) == 16_000


async def test_file_source_plays_in_real_time_then_stops() -> None:
    audio = np.zeros(FRAME_SAMPLES * 2, dtype=np.int16)
    source = FileSource(audio, realtime=True, speed=20.0, tail_s=0.16)
    frames = [frame async for frame in source.frames()]
    assert len(frames) == 4  # 2 trames du fichier + 0,16 s de silence
    assert source.finished_at is not None


async def test_a_silent_microphone_is_reported(fake_sd: types.SimpleNamespace) -> None:
    mic = MicrophoneSource(None, silent_after_s=0.05)
    with pytest.raises(MicrophoneSilentError):
        async for _ in mic.frames():
            pass
    assert fake_sd.created[0].closed
