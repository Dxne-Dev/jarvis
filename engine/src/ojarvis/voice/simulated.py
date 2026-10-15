"""Audio simulé pour les tests de bout en bout : aucun micro, aucun haut-parleur, aucun modèle.

Activé seulement en mode développement (`OJARVIS_FAKE_AUDIO=1`). Le « micro » envoie du
silence ; quand on demande à Jarvis d'écouter (bouton micro), il envoie un peu plus d'une
seconde de « parole », que le faux transcripteur rend par une phrase fixe. Tout le reste
du chemin est réel : pipeline, chat, mémoire, traces, événements vers l'interface.
"""

from __future__ import annotations

import asyncio
import math
import os
import time
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any

import numpy as np

from ojarvis.voice.audio import FRAME_S, FRAME_SAMPLES, RATE, Frame, MemorySink, Pcm
from ojarvis.voice.stt import Transcript
from ojarvis.voice.tts import AudioChunk

DEFAULT_TRANSCRIPT = "Quelle heure est-il ?"


class SimulatedMic:
    def __init__(self, _device: str | None = None) -> None:
        self._speech_frames = 0
        self._closed = asyncio.Event()

    def speak(self, seconds: float = 1.2) -> None:
        self._speech_frames += round(seconds / FRAME_S)

    async def close(self) -> None:
        self._closed.set()

    async def frames(self) -> AsyncGenerator[Frame]:
        rng = np.random.default_rng(11)
        tone = (8000 * np.sin(2 * math.pi * 220 * np.arange(FRAME_SAMPLES) / RATE)).astype(np.int16)
        start = time.monotonic()
        index = 0
        while not self._closed.is_set():
            index += 1
            delay = start + index * FRAME_S - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            if self._speech_frames > 0:
                self._speech_frames -= 1
                pcm = tone
            else:
                pcm = rng.normal(0, 10, FRAME_SAMPLES).astype(np.int16)
            yield Frame(pcm, time.monotonic())


class SilentWake:
    """Le mot de réveil n'est jamais entendu : on passe par le bouton micro."""

    def score(self, pcm: Pcm) -> float:
        del pcm
        return 0.0

    def reset(self) -> None:
        return None


class LoudnessVad:
    def process(self, pcm: Pcm) -> float:
        rms = float(np.sqrt(np.mean(np.square(pcm.astype(np.float32)))))
        return 0.95 if rms > 1000 else 0.02

    def reset(self) -> None:
        return None


class ScriptedTranscriber:
    def __init__(self, text: str) -> None:
        self._text = text

    async def transcribe(self, audio: Pcm) -> Transcript:
        await asyncio.sleep(0.05)
        return Transcript(
            text=self._text, audio_s=len(audio) / RATE, duration_ms=50.0, avg_logprob=-0.2
        )


class SilentVoice:
    """Synthèse muette : 0,4 s de silence par phrase, au rythme réel."""

    name = "simulee"

    @property
    def available(self) -> bool:
        return True

    async def warm_up(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def stream(self, sentences: AsyncIterator[str]) -> AsyncGenerator[AudioChunk]:
        async for _sentence in sentences:
            await asyncio.sleep(0.05)
            yield AudioChunk(bytes(2 * 9600), 24_000)


class NoEcho:
    def load(self, source: str | None, sink: str | None) -> bool:
        del source, sink
        return False

    def unload(self) -> None:
        return None


def simulated_voice() -> dict[str, Any]:
    """Arguments de `VoiceService` pour une voix entièrement simulée."""
    mics: list[SimulatedMic] = []

    def make_mic(device: str | None) -> SimulatedMic:
        mics.append(SimulatedMic(device))
        return mics[-1]

    def on_listen() -> None:
        if mics:
            mics[-1].speak()

    text = os.environ.get("OJARVIS_FAKE_TRANSCRIPT", DEFAULT_TRANSCRIPT)
    return {
        "parts": {
            "wake": SilentWake(),
            "vad": LoudnessVad(),
            "stt": ScriptedTranscriber(text),
            "tts": SilentVoice(),
        },
        "source_factory": make_mic,
        "sink_factory": lambda _device: MemorySink(realtime=True),
        "echo": NoEcho(),
        "on_listen": on_listen,
    }
