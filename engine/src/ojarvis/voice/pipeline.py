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
import enum
import time
from collections import deque
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import numpy as np

from ojarvis.chat.service import ChatService
from ojarvis.core.clock import utc_now
from ojarvis.core.logs import get_logger
from ojarvis.events.bus import EventBus
from ojarvis.tracing.tracer import Tracer
from ojarvis.voice.audio import FRAME_S, AudioSink, AudioSource, Frame, Pcm, level
from ojarvis.voice.sentences import SentenceSplitter
from ojarvis.voice.stt import Transcriber, Transcript
from ojarvis.voice.tts import Synthesizer, TTSError
from ojarvis.voice.vad import Endpoint, EndpointConfig, Endpointer, SpeechDetector
from ojarvis.voice.wake import WakeDetector, mentions_jarvis, strip_wake_words

log = get_logger(__name__)

SPOKEN_LLM_ERROR = "Je n'arrive pas à joindre le modèle pour l'instant. Réessaie dans un moment."


class VoiceState(enum.StrEnum):
    OFF = "off"
    IDLE = "idle"  # en veille : seul le mot de réveil est écouté, en local
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    ERROR = "error"


@dataclass
class VoiceConfig:
    wake_threshold: float = 0.5
    #: Score « hésitant » : au-dessus, les 2 dernières secondes sont vérifiées par transcription.
    wake_candidate: float = 0.15
    verify_wake: bool = True
    verify_window_s: float = 2.0
    #: Audio gardé avant le début détecté de la phrase, pour ne pas couper la première syllabe.
    preroll_s: float = 0.35
    #: Après une réponse, Jarvis écoute encore ce temps-là sans mot de réveil (0 = jamais).
    follow_up_s: float = 6.0
    #: Interrompre Jarvis en parlant (sinon, seulement en redisant « Hey Jarvis »).
    barge_in: bool = True
    barge_in_s: float = 0.4
    barge_in_threshold: float = 0.7
    #: Une nouvelle conversation commence après ce silence entre deux tours.
    conversation_idle_s: float = 600.0
    endpoint: EndpointConfig = field(default_factory=EndpointConfig)


@dataclass
class _Candidate:
    started_at: float
    best: float
    frames_left: int


@dataclass
class _Listening:
    opened_at: float
    frames: list[Frame] = field(default_factory=list)
    speculative: asyncio.Task[Transcript] | None = None
    speculative_frames: int = 0
    follow_up: bool = False
    #: Déjà relancé une fois après une transcription vide (« Hey Jarvis » … silence).
    retried: bool = False


@dataclass
class TurnReport:
    text: str
    reply: str
    latency_ms: float | None
    stt_ms: float
    speculative: bool
    first_token_ms: float | None
    tts_engine: str | None
    conversation_id: str | None
    trace_id: str | None
    interrupted: bool = False


class VoicePipeline:
    def __init__(
        self,
        *,
        source: AudioSource,
        sink: AudioSink,
        wake: WakeDetector,
        vad: SpeechDetector,
        stt: Transcriber,
        tts: Synthesizer,
        chat: ChatService,
        bus: EventBus,
        tracer: Tracer,
        config: VoiceConfig | None = None,
        on_turn: Callable[[TurnReport], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._clock = clock
        self._source = source
        self._sink = sink
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

    def _wake_step(self, frame: Frame) -> None:
        cfg = self.config
        score = self._wake.score(frame.pcm)
        if score >= cfg.wake_threshold:
            self._woke(frame.at, score, verified=False)
            return
        if not cfg.verify_wake or self._verify is not None:
            return
        candidate = self._candidate
        if candidate is None:
            if score >= cfg.wake_candidate:
                self._candidate = _Candidate(frame.at, score, frames_left=3)
            return
        candidate.best = max(candidate.best, score)
        candidate.frames_left -= 1
        if candidate.frames_left <= 0:
            self._candidate = None
            audio = self._recent_audio(cfg.verify_window_s)
            self._verify = asyncio.create_task(self._verify_wake(audio, candidate))

    async def _verify_wake(self, audio: Pcm, candidate: _Candidate) -> None:
        try:
            transcript = await self._stt.transcribe(audio)
            if self._state == VoiceState.IDLE and mentions_jarvis(transcript.text):
                self._woke(candidate.started_at, candidate.best, verified=True)
            else:
                log.debug("wake_rejected", score=round(candidate.best, 2))
        except Exception:
            log.exception("wake_verification_failed")
        finally:
            self._verify = None

    def _woke(self, at: float, score: float, *, verified: bool) -> None:
        self._candidate = None
        # Le détecteur garde ~1,5 s d'audio en mémoire : sans remise à zéro, il
        # réentendrait ce même « Hey Jarvis » pendant la réponse et la couperait.
        self._wake.reset()
        self._spawn(
            self._bus.publish("voice.wake", {"score": round(score, 3), "verified": verified})
        )
        self._spawn(self._tts.warm_up())
        self._start_listening(at, replay=True)

    def _recent_audio(self, seconds: float) -> Pcm:
        count = max(1, int(seconds / FRAME_S))
        frames = list(self._history)[-count:]
        return np.concatenate([f.pcm for f in frames])

    # ------------------------------------------------------------------ écoute

    def _start_listening(
        self, at: float, *, replay: bool, follow_up: bool = False, timeout_s: float | None = None
    ) -> None:
        self._vad.reset()
        self._endpointer.reset(at, timeout_s=timeout_s)
        self._listening = _Listening(opened_at=at, follow_up=follow_up)
        self._barge_since = None
        self._set_state(VoiceState.LISTENING)
        if replay:
            # Les trames déjà reçues depuis le réveil passent tout de suite par le VAD :
            # la question qui suit « Hey Jarvis » sans pause n'est pas perdue.
            for frame in [f for f in self._history if f.at > at]:
                if self._listening is None or self._state != VoiceState.LISTENING:
                    break
                self._listen_step(frame)

    def _listen_step(self, frame: Frame) -> None:
        listening = self._listening
        if listening is None:
            return
        listening.frames.append(frame)
        prob = self._vad.process(frame.pcm)
        event = self._endpointer.update(prob, frame.at, FRAME_S)
        if event == Endpoint.PAUSE:
            audio = self._utterance_audio(listening)
            listening.speculative = asyncio.create_task(self._stt.transcribe(audio))
            listening.speculative_frames = len(listening.frames)
        elif event == Endpoint.RESUME and listening.speculative is not None:
            listening.speculative.cancel()
            listening.speculative = None
        elif event == Endpoint.END:
            self._finish_listening(listening)
        elif event == Endpoint.TIMEOUT:
            if listening.speculative is not None:
                listening.speculative.cancel()
            self._listening = None
            if not listening.follow_up:
                self._spawn(self._bus.publish("voice.timeout", {}, persist=False))
            self._go_idle()

    def _utterance_audio(self, listening: _Listening, upto: int | None = None) -> Pcm:
        start = self._endpointer.speech_start_at or listening.opened_at
        first = start - self.config.preroll_s
        frames = [f for f in listening.frames[:upto] if f.at > first]
        if len(frames) < len(listening.frames[:upto]) and first < listening.opened_at:
            # Le début de la phrase précède l'ouverture de l'écoute : on reprend l'historique.
            earlier = [f for f in self._history if first < f.at <= listening.opened_at]
            frames = earlier + frames
        return np.concatenate([f.pcm for f in frames]) if frames else np.zeros(0, np.int16)

    def _finish_listening(self, listening: _Listening) -> None:
        speech_end = self._endpointer.last_voice_at or listening.frames[-1].at
        audio = self._utterance_audio(listening)
        speculative = listening.speculative
        self._listening = None
        self._turn_audio = list(listening.frames)
        self._set_state(VoiceState.THINKING)
        self._turn = asyncio.create_task(
            self._run_turn(audio, speculative, speech_end, retried=listening.retried)
        )

    # ------------------------------------------------------------------ pendant la réponse

    async def _busy_step(self, frame: Frame) -> None:
        cfg = self.config
        score = self._wake.score(frame.pcm)
        if score >= max(cfg.wake_threshold, 0.6):
            await self._cancel_turn(by="mot de réveil")
            self._woke(frame.at, score, verified=False)
            return
        if not cfg.barge_in:
            return
        prob = self._vad.process(frame.pcm)
        if prob < cfg.barge_in_threshold:
            self._barge_since = None
            return
        if self._barge_since is None:
            self._barge_since = frame.at - FRAME_S
        if frame.at - self._barge_since < cfg.barge_in_s:
            return
        since = self._barge_since
        if self._state == VoiceState.THINKING:
            # La phrase n'était pas finie : on reprend l'écoute avec ce qui a déjà été dit.
            previous = self._turn_audio
            await self._cancel_turn(by="suite de la phrase")
            after = previous[-1].at if previous else since - FRAME_S
            self._start_listening(previous[0].at if previous else since, replay=False)
            if self._listening is not None:
                self._listening.frames = previous + [f for f in self._history if f.at > after]
                self._endpointer.speaking = True
                self._endpointer.speech_start_at = previous[0].at if previous else since
                self._endpointer.last_voice_at = frame.at
            return
        await self._cancel_turn(by="voix")
        self._start_listening(since - FRAME_S, replay=True)

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
        self._wake.reset()
        self._candidate = None
        self._set_state(VoiceState.IDLE)

    # ------------------------------------------------------------------ un tour

    def _conversation_id(self) -> str | None:
        if self._conversation is None:
            return None
        conversation_id, last = self._conversation
        if self._clock() - last > self.config.conversation_idle_s:
            return None
        return conversation_id

    async def _run_turn(
        self,
        audio: Pcm,
        speculative: asyncio.Task[Transcript] | None,
        speech_end: float,
        *,
        retried: bool,
    ) -> None:
        try:
            await self._turn_steps(audio, speculative, speech_end, retried=retried)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("voice_turn_failed")
            self._turn = None
            self._sink.stop()
            await self._bus.publish("voice.error", {"message": f"{type(exc).__name__}"})
            self._go_idle()

    async def _turn_steps(
        self,
        audio: Pcm,
        speculative: asyncio.Task[Transcript] | None,
        speech_end: float,
        *,
        retried: bool,
    ) -> None:
        stt_started = utc_now()
        used_speculative = False
        transcript: Transcript | None = None
        if speculative is not None and not speculative.cancelled():
            with contextlib.suppress(Exception):
                transcript = await speculative
                used_speculative = True
        if transcript is None:
            transcript = await self._stt.transcribe(audio)
        text = strip_wake_words(transcript.text)
        if not _meaningful(text, transcript):
            self._turn = None
            if not retried:
                # « Hey Jarvis » puis silence : on attend encore la question.
                self._start_listening(self._clock(), replay=False)
                if self._listening is not None:
                    self._listening.retried = True
            else:
                self._go_idle()
            return
        report = await self._answer(text, transcript, stt_started, used_speculative, speech_end)
        self.last_report = report
        if self._on_turn is not None:
            self._on_turn(report)
        self._turn = None
        if self.config.follow_up_s > 0:
            self._start_listening(
                self._clock(), replay=False, follow_up=True, timeout_s=self.config.follow_up_s
            )
        else:
            self._go_idle()

    async def _answer(
        self,
        text: str,
        transcript: Transcript,
        stt_started: Any,
        speculative: bool,
        speech_end: float,
    ) -> TurnReport:
        await self._bus.publish("voice.transcript", {"text": text}, persist=False)
        reply: list[str] = []
        done: dict[str, Any] = {}
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        async with self._tracer.trace("Tour vocal", kind="voice", meta={"canal": "voix"}) as trace:
            stt_ms = transcript.duration_ms
            await self._tracer.add_span(
                "transcription",
                kind="stt",
                started_at=stt_started - timedelta(milliseconds=stt_ms if speculative else 0),
                duration_ms=stt_ms,
                audio_s=transcript.audio_s,
                anticipee=speculative,
                modele="whisper-base",
            )
            producer = asyncio.create_task(
                self._produce(text, queue, reply, done, learn=transcript.reliable)
            )
            self._sink.begin()
            first_chunk: float | None = None
            engine = None
            try:
                async with self._tracer.span("synthèse vocale", kind="tts") as span:
                    async with contextlib.aclosing(self._tts.stream(_sentences(queue))) as chunks:
                        async for chunk in chunks:
                            if first_chunk is None:
                                first_chunk = self._clock()
                                self._set_state(VoiceState.SPEAKING)
                            await self._sink.play(chunk.pcm, chunk.rate)
                    engine = getattr(self._tts, "last_engine", None) or self._tts.name
                    span.set(moteur=engine)
                await self._sink.drain()
            except TTSError as error:
                log.warning("tts_failed", error=str(error))
                trace.fail(f"synthèse vocale : {error}")
            finally:
                if not producer.done():
                    producer.cancel()
                with contextlib.suppress(BaseException):
                    await producer
            first_audio = self._sink.first_audio_at
            latency = round((first_audio - speech_end) * 1000, 1) if first_audio else None
            trace.set(
                latence_ms=latency,
                transcription_ms=stt_ms,
                voix=engine,
                confiance=transcript.avg_logprob,
                apprentissage=transcript.reliable,
            )
            report = TurnReport(
                text=text,
                reply="".join(reply).strip(),
                latency_ms=latency,
                stt_ms=stt_ms,
                speculative=speculative,
                first_token_ms=done.get("first_token_ms"),
                tts_engine=engine,
                conversation_id=done.get("conversation_id"),
                trace_id=trace.id,
            )
        await self._bus.publish(
            "voice.turn",
            {
                "latency_ms": report.latency_ms,
                "stt_ms": report.stt_ms,
                "speculative": report.speculative,
                "first_token_ms": report.first_token_ms,
                "tts_engine": report.tts_engine,
                "conversation_id": report.conversation_id,
                "trace_id": report.trace_id,
            },
        )
        return report

    async def _produce(
        self,
        text: str,
        queue: asyncio.Queue[str | None],
        reply: list[str],
        done: dict[str, Any],
        *,
        learn: bool,
    ) -> None:
        splitter = SentenceSplitter()
        try:
            events = self._chat.respond(
                text=text, conversation_id=self._conversation_id(), channel="voice", learn=learn
            )
            async with contextlib.aclosing(events) as stream:
                async for event in stream:
                    if event.type == "start":
                        self._conversation = (event.data["conversation_id"], self._clock())
                        done["conversation_id"] = event.data["conversation_id"]
                    elif event.type == "delta":
                        reply.append(event.data["text"])
                        for sentence in splitter.feed(event.data["text"]):
                            await queue.put(sentence)
                    elif event.type == "done":
                        done.update(event.data)
                    elif event.type == "error":
                        for sentence in splitter.flush():
                            await queue.put(sentence)
                        await queue.put(SPOKEN_LLM_ERROR)
            for sentence in splitter.flush():
                await queue.put(sentence)
            if self._conversation is not None:
                self._conversation = (self._conversation[0], self._clock())
        finally:
            await queue.put(None)


async def _sentences(queue: asyncio.Queue[str | None]) -> AsyncIterator[str]:
    while (sentence := await queue.get()) is not None:
        yield sentence


def _meaningful(text: str, transcript: Transcript) -> bool:
    """Assez de parole pour mériter une réponse (et pas une hallucination sur du bruit)."""
    words = [w for w in text.split() if any(c.isalnum() for c in w)]
    if not words:
        return False
    return not (transcript.no_speech_prob > 0.6 and len(words) < 3)
