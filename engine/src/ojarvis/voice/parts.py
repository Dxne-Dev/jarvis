"""Ce que partagent les morceaux du pipeline vocal (`listening.py`, `turn.py`) : l'état et les
méthodes de `VoicePipeline`, déclarés ici pour la vérification des types. À l'exécution,
c'est `VoicePipeline` qui les porte : cette classe ne fait que les nommer.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ojarvis.chat.service import ChatService
    from ojarvis.events.bus import EventBus
    from ojarvis.tracing.tracer import Tracer
    from ojarvis.voice.audio import AudioSink, AudioSource, Frame, Pcm
    from ojarvis.voice.listening import _Candidate, _Listening
    from ojarvis.voice.states import VoiceConfig, VoiceState
    from ojarvis.voice.stt import CloudTranscriber, Transcriber, Transcript
    from ojarvis.voice.stt_online import StreamingTranscriber, SttStream
    from ojarvis.voice.tts import Synthesizer
    from ojarvis.voice.turn import TurnReport
    from ojarvis.voice.vad import Endpointer, SpeechDetector
    from ojarvis.voice.wake import WakeDetector


class VoiceParts:
    config: VoiceConfig
    streaming_stt: StreamingTranscriber | None
    cloud_stt: CloudTranscriber | None
    last_report: TurnReport | None
    frames_seen: int
    _clock: Callable[[], float]
    _source: AudioSource
    _sink: AudioSink
    _wake: WakeDetector | None
    _vad: SpeechDetector
    _stt: Transcriber
    _tts: Synthesizer
    _chat: ChatService
    _bus: EventBus
    _tracer: Tracer
    _on_turn: Callable[[TurnReport], None] | None
    _endpointer: Endpointer
    _history: deque[Frame]
    _state: VoiceState
    _candidate: _Candidate | None
    _verify: asyncio.Task[None] | None
    _listening: _Listening | None
    _turn: asyncio.Task[None] | None
    _turn_audio: list[Frame]
    _barge_since: float | None
    _listen_request: bool
    _dictation: asyncio.Future[str] | None
    _conversation: tuple[str, float] | None
    _tasks: set[asyncio.Task[Any]]

    if TYPE_CHECKING:
        # Portées par VoicePipeline (pipeline.py) :
        def _set_state(self, state: VoiceState) -> None: ...
        def _spawn(self, coroutine: Coroutine[Any, Any, Any]) -> None: ...
        def _end_dictation(self, text: str) -> bool: ...
        async def _speak(self, text: str) -> None: ...
        async def _cancel_turn(self, *, by: str) -> None: ...
        def _go_idle(self) -> None: ...

        # Portées par Listening (listening.py) :
        def _start_listening(
            self,
            at: float,
            *,
            replay: bool,
            follow_up: bool = False,
            timeout_s: float | None = None,
        ) -> None: ...

        # Portées par Turns (turn.py) :
        async def _run_turn(
            self,
            audio: Pcm,
            speculative: asyncio.Task[Transcript] | None,
            speech_end: float,
            *,
            retried: bool,
            stream: SttStream | None = None,
            speculative_engine: str = "whisper",
        ) -> None: ...
