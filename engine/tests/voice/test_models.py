"""Vrais modèles locaux sur de l'audio de synthèse (espeak-ng).

Ignorés si les modèles ne sont pas encore téléchargés sur la machine ou si espeak-ng
manque. Le corpus complet (Piper, espeak-ng, Cartesia) se mesure avec tools/voice_bench.py.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pytest

from ojarvis.voice.audio import FRAME_SAMPLES, Pcm, read_wav
from ojarvis.voice.stt import WHISPER_FILES, WhisperTranscriber
from ojarvis.voice.vad import SileroVad
from ojarvis.voice.wake import WAKE_FILES, OpenWakeWord, mentions_jarvis

MODELS = Path.home() / ".cache" / "o-jarvis" / "models"
WAKE_DIR = MODELS / "openwakeword"
WHISPER_DIR = MODELS / "faster-whisper-base"

ESPEAK = shutil.which("espeak-ng")
needs_espeak = pytest.mark.skipif(ESPEAK is None, reason="espeak-ng absent")
needs_wake = pytest.mark.skipif(
    not all((WAKE_DIR / name).is_file() for name in WAKE_FILES), reason="openWakeWord absent"
)
needs_whisper = pytest.mark.skipif(
    not all((WHISPER_DIR / name).is_file() for name in WHISPER_FILES), reason="Whisper absent"
)


def speak(voice: str, text: str) -> Pcm:
    with tempfile.TemporaryDirectory() as folder:
        out = Path(folder) / "voix.wav"
        subprocess.run(  # noqa: S603 — arguments fixes du test
            [ESPEAK or "espeak-ng", "-v", voice, "-s", "150", "-w", str(out), text],
            check=True,
            capture_output=True,
        )
        return read_wav(out)


def framed(audio: Pcm) -> list[Pcm]:
    silence = np.zeros(16_000, dtype=np.int16)
    padded = np.concatenate([silence, audio, silence])
    return [
        padded[i : i + FRAME_SAMPLES] for i in range(0, len(padded) - FRAME_SAMPLES, FRAME_SAMPLES)
    ]


@needs_espeak
@needs_wake
@pytest.mark.parametrize("voice", ["en-us", "en", "en+f3"])
def test_hey_jarvis_is_detected(voice: str) -> None:
    detector = OpenWakeWord(WAKE_DIR)
    best = max(detector.score(frame) for frame in framed(speak(voice, "Hey Jarvis")))
    assert best >= 0.5


@needs_espeak
@needs_wake
def test_an_ordinary_sentence_does_not_wake_jarvis() -> None:
    detector = OpenWakeWord(WAKE_DIR)
    audio = speak("fr", "Bonjour, il fait beau aujourd'hui, on va se promener au parc.")
    assert max(detector.score(frame) for frame in framed(audio)) < 0.15


@needs_espeak
def test_vad_hears_speech_and_not_silence() -> None:
    vad = SileroVad()
    probs = [vad.process(frame) for frame in framed(speak("fr", "Bonjour, comment ça va ?"))]
    assert max(probs[:8]) < 0.3  # la seconde de silence du début
    assert max(probs) > 0.8


@needs_espeak
@needs_whisper
def test_whisper_short_window_transcribes_and_finds_jarvis() -> None:
    stt = WhisperTranscriber(WHISPER_DIR)
    audio = np.concatenate([speak("en-us", "Hey Jarvis"), speak("fr", "bonjour")])
    transcript = stt.transcribe_sync(audio)
    assert mentions_jarvis(transcript.text)
    assert transcript.duration_ms < 3000
