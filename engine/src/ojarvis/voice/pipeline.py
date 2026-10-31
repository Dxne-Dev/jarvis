"""Pipeline vocal : mot de réveil → écoute → transcription → réponse du modèle → parole.

Une seule boucle lit le micro, trame après trame, et ne bloque jamais : la transcription,
le modèle et la synthèse tournent dans des tâches à part. L'écoute continue donc pendant
que Jarvis réfléchit ou parle, ce qui permet de l'interrompre.

La latence mesurée va de la fin de la phrase (dernière trame où le VAD entend la voix)
au premier son de la réponse qui sort du haut-parleur.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import deque
from collections.abc import Callable
from typing import Any

from ojarvis.chat.service import ChatService
from ojarvis.core.logs import get_logger
from ojarvis.events.bus import EventBus
from ojarvis.tracing.tracer import Tracer
from ojarvis.voice.audio import FRAME_S, AudioSink, AudioSource, Frame, level
from ojarvis.voice.listening import Listening, _Candidate, _Listening
from ojarvis.voice.sentences import SentenceSplitter
from ojarvis.voice.states import VoiceConfig, VoiceState
from ojarvis.voice.stt import CloudTranscriber, Transcriber
from ojarvis.voice.stt_online import StreamingTranscriber
from ojarvis.voice.tts import Synthesizer, TTSError
from ojarvis.voice.turn import (
    TurnReport,
    Turns,
    _sentences,
)
from ojarvis.voice.vad import Endpointer, SpeechDetector
from ojarvis.voice.wake import WakeDetector

log = get_logger(__name__)


class VoicePipeline(Listening, Turns):
    def __init__(
        self,
        *,
        source: AudioSource,
        sink: AudioSink,
        wake: WakeDetector | None,
        vad: SpeechDetector,
        stt: Transcriber,
        tts: Synthesizer,
        chat: ChatService,
        bus: EventBus,
        tracer: Tracer,
        config: VoiceConfig | None = None,
        on_turn: Callable[[TurnReport], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        streaming_stt: StreamingTranscriber | None = None,
        cloud_stt: CloudTranscriber | None = None,
    ) -> None:
        self._clock = clock
        #: Transcription en ligne : en flux (Cartesia) ou par phrase (Groq). `None` partout :
        #: Whisper local seulement. Modifiables à chaud ; Whisper local reste le secours.
        self.streaming_stt = streaming_stt
        self.cloud_stt = cloud_stt
        self._source = source
        self._sink = sink
        #: Sans détecteur (profil « Tout Meta ») : on parle après le raccourci ou le bouton micro.
        self._wake = wake
        self._vad = vad
        self._stt = stt
        self._tts = tts
        self._chat = chat
        self._bus = bus
        self._tracer = tracer
        self.config = config or VoiceConfig()
        self._on_turn = on_turn
        self._endpointer = Endpointer(self.config.endpoint)
        self._history: deque[Frame] = deque(maxlen=int(4.0 / FRAME_S))
        self._state = VoiceState.IDLE
        self._candidate: _Candidate | None = None
        self._verify: asyncio.Task[None] | None = None
        self._listening: _Listening | None = None
        self._turn: asyncio.Task[None] | None = None
        self._turn_audio: list[Frame] = []
        self._barge_since: float | None = None
        self._listen_request = False
        #: Une dictée du terminal en attente (#10) : la prochaine phrase lui revient, sans
        #: réponse parlée ni tour de conversation vocal.
        self._dictation: asyncio.Future[str] | None = None
        self._conversation: tuple[str, float] | None = None
        self._tasks: set[asyncio.Task[Any]] = set()
        self.last_report: TurnReport | None = None
        #: Trames reçues du micro : le diagnostic « le micro transmet-il ? ».
        self.frames_seen = 0

    # ------------------------------------------------------------------ état

    @property
    def state(self) -> VoiceState:
        return self._state

    def _set_state(self, state: VoiceState) -> None:
        if state == self._state:
            return
        self._state = state
        self._spawn(self._bus.publish("voice.state", {"state": state.value}, persist=False))

    def _spawn(self, coroutine: Any) -> None:
        task = asyncio.ensure_future(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def listen_now(self) -> None:
        """Parler sans mot de réveil (raccourci clavier, bouton micro) ; coupe Jarvis s'il parle."""
        self._listen_request = True

    def dictate(self) -> asyncio.Future[str]:
        """Le terminal écoute une phrase, comme avec le bouton micro de l'app : pas de mot de
        réveil à dire, et rien ne quitte la machine avant que l'on parle. La phrase lui revient ;
        il la montre et la traite comme une demande écrite. Une seule écoute à la fois : une
        dictée déjà en cours est rendue telle quelle."""
        if self._dictation is None or self._dictation.done():
            self._dictation = asyncio.get_running_loop().create_future()
            self.listen_now()
        return self._dictation

    def cancel_dictation(self) -> None:
        self._end_dictation("")

    def _end_dictation(self, text: str) -> bool:
        """Rend la phrase au terminal qui l'attend ; faux s'il n'en attend pas."""
        dictation, self._dictation = self._dictation, None
        if dictation is None or dictation.done():
            return False
        dictation.set_result(text)
        return True

    def say(self, text: str) -> bool:
        """Dire un texte de lui-même (ex. le briefing du matin), seulement s'il est en veille.

        On peut l'interrompre comme une réponse : « Hey Jarvis » ou en parlant."""
        if self._state != VoiceState.IDLE or self._turn is not None or not text.strip():
            return False
        self._turn = asyncio.ensure_future(self._speak(text))
        return True

    async def _speak(self, text: str) -> None:
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        splitter = SentenceSplitter()
        for sentence in [*splitter.feed(text), *splitter.flush()]:
            queue.put_nowait(sentence)
        queue.put_nowait(None)
        self._set_state(VoiceState.SPEAKING)
        self._sink.begin()
        try:
            async with contextlib.aclosing(
                self._tts.stream(_sentences(queue, self._bus))
            ) as chunks:
                async for chunk in chunks:
                    await self._sink.play(chunk.pcm, chunk.rate)
            await self._sink.drain()
        except TTSError as error:
            log.warning("tts_failed", error=str(error))
        finally:
            if self._turn is asyncio.current_task():
                self._turn = None
            if self._state == VoiceState.SPEAKING:
                self._go_idle()

    async def interrupt(self, *, by: str = "ui") -> None:
        """Coupe la réponse en cours et revient en veille."""
        if self._turn is not None or self._listening is not None:
            await self._cancel_turn(by=by)
            self._listening = None
            self._go_idle()

    # ------------------------------------------------------------------ boucle

    async def run(self) -> None:
        try:
            async for frame in self._source.frames():
                self.frames_seen += 1
                self._history.append(frame)
                try:
                    await self._on_frame(frame)
                except Exception:
                    log.exception("voice_frame_failed")
                    await self._cancel_turn(by="erreur")
                    self._listening = None
                    self._go_idle()
        finally:
            await self._cancel_turn(by="arret")
            if self._verify is not None:
                self._verify.cancel()
            self._sink.stop()
            # Les derniers événements (état, interruption) partent avant l'arrêt.
            pending = list(self._tasks)
            if pending:
                _, late = await asyncio.wait(pending, timeout=1.0)
                for task in late:
                    task.cancel()

    async def _on_frame(self, frame: Frame) -> None:
        if self._listen_request:
            self._listen_request = False
            if self._turn is not None:
                await self._cancel_turn(by="raccourci")
            self._start_listening(frame.at, replay=False)
        state = self._state
        if state == VoiceState.IDLE:
            self._wake_step(frame)
        elif state == VoiceState.LISTENING:
            self._listen_step(frame)
            self._publish_level("mic", level(frame.pcm))
        elif state in (VoiceState.THINKING, VoiceState.SPEAKING):
            await self._busy_step(frame)
            if state == VoiceState.SPEAKING:
                self._publish_level("speaker", self._sink.level)

    def _publish_level(self, source: str, value: float) -> None:
        self._spawn(
            self._bus.publish(
                "voice.level", {"source": source, "level": round(value, 3)}, persist=False
            )
        )

    # ------------------------------------------------------------------ réveil

    # ------------------------------------------------------------------ écoute

    # ------------------------------------------------------------------ pendant la réponse

    async def _cancel_turn(self, *, by: str) -> None:
        turn, self._turn = self._turn, None
        if turn is None or turn.done():
            return
        self._sink.stop()
        turn.cancel()
        with contextlib.suppress(BaseException):
            await turn
        self._spawn(self._bus.publish("voice.interrupted", {"by": by}))

    def _go_idle(self) -> None:
        if self._wake is not None:
            self._wake.reset()
        self._candidate = None
        self._set_state(VoiceState.IDLE)

    # ------------------------------------------------------------------ un tour
