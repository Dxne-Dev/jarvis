"""Transcription locale en français : faster-whisper, modèle `base`, int8 sur le CPU.

Whisper encode toujours une fenêtre de 30 s, même pour une phrase de 2 s. Ici, la fenêtre
est réduite à 10 s quand la phrase est courte : l'encodeur va environ 4 fois plus vite
(0,45 s au lieu de 1,7 s sur cette machine) pour une transcription quasi identique.
Si ce chemin rapide échoue, on revient à la méthode standard de faster-whisper.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import anyio.to_thread
import numpy as np

from ojarvis.core.downloads import PinnedFile
from ojarvis.core.logs import get_logger
from ojarvis.voice.audio import RATE, Pcm

log = get_logger(__name__)

WHISPER_REVISION = "ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66"
WHISPER_BASE = f"https://huggingface.co/Systran/faster-whisper-base/resolve/{WHISPER_REVISION}"
WHISPER_FILES: dict[str, PinnedFile] = {
    "config.json": PinnedFile(
        f"{WHISPER_BASE}/config.json",
        "56a6d8110d311f19c8f0471e562832c7527f146b567275bfca59fcf7c184da9a",
    ),
    "model.bin": PinnedFile(
        f"{WHISPER_BASE}/model.bin",
        "d01c3014881c9c6f3133c182f3d2887eb6ca1c789a7538c5c007196857a0a6a9",
    ),
    "tokenizer.json": PinnedFile(
        f"{WHISPER_BASE}/tokenizer.json",
        "fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab",
    ),
    "vocabulary.txt": PinnedFile(
        f"{WHISPER_BASE}/vocabulary.txt",
        "34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913",
    ),
}

#: Au-delà, la fenêtre courte n'apporte plus rien : on encode la durée réelle (+ marge).
SHORT_WINDOW_S = 10
FRAMES_PER_S = 100


@dataclass(frozen=True)
class Transcript:
    text: str
    audio_s: float
    duration_ms: float
    no_speech_prob: float = 0.0


class Transcriber(Protocol):
    async def transcribe(self, audio: Pcm) -> Transcript: ...


class WhisperTranscriber:
    def __init__(self, folder: Path, *, threads: int = 4, language: str = "fr") -> None:
        self.folder = folder
        self._threads = threads
        self._language = language
        self._model: Any = None
        self._tokenizer: Any = None
        self._prompt: list[int] = []
        self._suppress: list[int] = []
        self._lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        from faster_whisper import WhisperModel  # noqa: PLC0415
        from faster_whisper.tokenizer import Tokenizer  # noqa: PLC0415
        from faster_whisper.transcribe import get_suppressed_tokens  # noqa: PLC0415

        with self._lock:
            if self._model is not None:
                return
            model = WhisperModel(
                str(self.folder), device="cpu", compute_type="int8", cpu_threads=self._threads
            )
            tokenizer = Tokenizer(
                model.hf_tokenizer, True, task="transcribe", language=self._language
            )
            self._prompt = [
                tokenizer.sot,
                tokenizer.language,
                tokenizer.transcribe,
                tokenizer.no_timestamps,
            ]
            self._suppress = list(get_suppressed_tokens(tokenizer, (-1,)) or [])
            self._tokenizer = tokenizer
            self._model = model

    async def transcribe(self, audio: Pcm) -> Transcript:
        return await anyio.to_thread.run_sync(self.transcribe_sync, audio)

    def transcribe_sync(self, audio: Pcm) -> Transcript:
        self.load()
        start = time.perf_counter()
        samples = audio.astype(np.float32) / 32768.0
        seconds = len(samples) / RATE
        with self._lock:
            try:
                text, no_speech = self._fast(samples, seconds)
            except Exception:
                log.exception("whisper_fast_path_failed")
                text, no_speech = self._standard(samples)
        return Transcript(
            text=text.strip(),
            audio_s=round(seconds, 2),
            duration_ms=round((time.perf_counter() - start) * 1000, 1),
            no_speech_prob=round(no_speech, 3),
        )

    def _fast(self, samples: Any, seconds: float) -> tuple[str, float]:
        import ctranslate2  # noqa: PLC0415

        short = seconds <= SHORT_WINDOW_S - 2
        window_s = SHORT_WINDOW_S if short else min(30, math.ceil(seconds) + 2)
        padded = np.zeros(window_s * RATE, dtype=np.float32)
        padded[: min(len(samples), len(padded))] = samples[: len(padded)]
        features = self._model.feature_extractor(padded)[:, : window_s * FRAMES_PER_S]
        encoded = self._model.model.encode(
            ctranslate2.StorageView.from_array(np.ascontiguousarray(features[None]))
        )
        result = self._model.model.generate(
            encoded,
            [self._prompt],
            beam_size=1,
            max_length=min(448, 24 + int(seconds * 10)),
            suppress_blank=True,
            suppress_tokens=self._suppress,
            return_no_speech_prob=True,
        )[0]
        tokens = [t for t in result.sequences_ids[0] if t < self._tokenizer.eot]
        return self._tokenizer.decode(tokens), float(result.no_speech_prob)

    def _standard(self, samples: Any) -> tuple[str, float]:
        segments, _ = self._model.transcribe(
            samples,
            language=self._language,
            beam_size=1,
            vad_filter=False,
            condition_on_previous_text=False,
            without_timestamps=True,
        )
        parts = list(segments)
        no_speech = max((s.no_speech_prob for s in parts), default=1.0)
        return " ".join(s.text.strip() for s in parts), no_speech
