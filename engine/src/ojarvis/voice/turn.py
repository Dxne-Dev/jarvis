"""Un tour vocal : la phrase transcrite (en ligne si possible, sinon en local), la réponse
du chat dite phrase par phrase, et le compte rendu du tour (latence, moteurs utilisés).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from ojarvis.core.clock import utc_now
from ojarvis.core.logs import get_logger
from ojarvis.events.bus import EventBus
from ojarvis.voice.audio import FRAME_SAMPLES, Pcm
from ojarvis.voice.parts import VoiceParts
from ojarvis.voice.sentences import SentenceSplitter
from ojarvis.voice.states import SPOKEN_LLM_ERROR, SPOKEN_STT_ERROR, VoiceState
from ojarvis.voice.stt import Transcript
from ojarvis.voice.stt_online import StreamingTranscriber, SttStream
from ojarvis.voice.tts import TTSError
from ojarvis.voice.wake import strip_wake_words

log = get_logger(__name__)

#: Modèle de transcription noté dans la trace, selon le moteur utilisé.
STT_MODELS = {
    "cartesia": "cartesia-ink-2",
    "groq": "groq-whisper-large-v3",
    "meta": "muse-voice-transcribe-1.0",
}


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
    stt_engine: str = "whisper"


async def _transcribe_at_once(engine: StreamingTranscriber, audio: Pcm) -> Transcript:
    """Une phrase déjà enregistrée, envoyée d'un bloc à une transcription en flux."""
    stream = engine.open()
    try:
        for start in range(0, len(audio), FRAME_SAMPLES):
            stream.send(audio[start : start + FRAME_SAMPLES])
        return await stream.finish(timeout_s=3.0)
    finally:
        await stream.cancel()


async def _sentences(queue: asyncio.Queue[str | None], bus: EventBus) -> AsyncIterator[str]:
    """Phrases à dire ; chacune part aussi vers l'interface, en sous-titre."""
    while (sentence := await queue.get()) is not None:
        await bus.publish("voice.sentence", {"text": sentence}, persist=False)
        yield sentence


def _meaningful(text: str, transcript: Transcript) -> bool:
    """Assez de parole pour mériter une réponse (et pas une hallucination sur du bruit)."""
    words = [w for w in text.split() if any(c.isalnum() for c in w)]
    if not words:
        return False
    return not (transcript.no_speech_prob > 0.6 and len(words) < 3)


class Turns(VoiceParts):
    """Un tour : transcrire, répondre, dire (mélangée à `VoicePipeline`)."""

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
        stream: SttStream | None = None,
        speculative_engine: str = "whisper",
    ) -> None:
        try:
            await self._turn_steps(
                audio,
                speculative,
                speech_end,
                retried=retried,
                stream=stream,
                speculative_engine=speculative_engine,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("voice_turn_failed")
            self._turn = None
            self._sink.stop()
            await self._bus.publish("voice.error", {"message": f"{type(exc).__name__}"})
            self._go_idle()

    def _stt_fallback(self, exc: BaseException) -> None:
        log.warning("stt_fallback", error=str(exc))
        self._spawn(self._bus.publish("voice.stt_fallback", {"reason": str(exc)[:200]}))

    async def _transcribe(
        self,
        audio: Pcm,
        speculative: asyncio.Task[Transcript] | None,
        stream: SttStream | None,
        speculative_engine: str = "whisper",
    ) -> tuple[Transcript, bool, str]:
        """Texte de la phrase : en ligne si possible, sinon Whisper local (anticipé ou non)."""
        if stream is not None:
            try:
                return await stream.finish(timeout_s=2.5), True, "cartesia"
            except Exception as exc:
                self._stt_fallback(exc)
            finally:
                self._spawn(stream.cancel())  # sans attendre la fermeture de la connexion
        cloud_failed = False
        if speculative is not None and not speculative.cancelled():
            try:
                return await speculative, True, speculative_engine
            except Exception as exc:
                if speculative_engine != "whisper":
                    self._stt_fallback(exc)
                    cloud_failed = True
        cloud = self.cloud_stt
        if cloud is not None and cloud.available and stream is None and not cloud_failed:
            try:
                return await cloud.transcribe(audio), False, getattr(cloud, "name", "en ligne")
            except Exception as exc:
                self._stt_fallback(exc)
                cloud_failed = True
        relay = self.streaming_stt
        if cloud_failed and relay is not None and relay.available:
            # Groq indisponible : la phrase déjà enregistrée part d'un bloc chez Cartesia.
            try:
                return await _transcribe_at_once(relay, audio), False, "cartesia"
            except Exception as exc:
                self._stt_fallback(exc)
        return await self._stt.transcribe(audio), False, getattr(self._stt, "name", "whisper")

    async def _turn_steps(
        self,
        audio: Pcm,
        speculative: asyncio.Task[Transcript] | None,
        speech_end: float,
        *,
        retried: bool,
        stream: SttStream | None = None,
        speculative_engine: str = "whisper",
    ) -> None:
        stt_started = utc_now()
        try:
            transcript, used_speculative, stt_engine = await self._transcribe(
                audio, speculative, stream, speculative_engine
            )
        except Exception as exc:
            # Plus aucun moteur (« Tout Meta » n'a que Muse Voice Transcribe) : Jarvis le dit.
            log.warning("stt_failed", error=str(exc))
            await self._bus.publish("voice.error", {"message": "transcription"})
            self._end_dictation("")
            await self._speak(SPOKEN_STT_ERROR)
            return
        text = strip_wake_words(transcript.text)
        if not _meaningful(text, transcript):
            self._turn = None
            if not retried:
                # « Hey Jarvis » puis silence : on attend encore la question.
                self._start_listening(self._clock(), replay=False)
                if self._listening is not None:
                    self._listening.retried = True
            else:
                self._end_dictation("")
                self._go_idle()
            return
        if self._end_dictation(text):
            # La phrase est pour le terminal : il la traite comme une demande écrite.
            self._turn = None
            self._go_idle()
            return
        report = await self._answer(
            text,
            transcript,
            stt_started=stt_started,
            speculative=used_speculative,
            speech_end=speech_end,
            stt_engine=stt_engine,
        )
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
        *,
        stt_started: Any,
        speculative: bool,
        speech_end: float,
        stt_engine: str = "whisper",
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
                modele=STT_MODELS.get(stt_engine, "whisper-base"),
            )
            producer = asyncio.create_task(
                self._produce(text, queue, reply, done, learn=transcript.reliable)
            )
            self._sink.begin()
            first_chunk: float | None = None
            engine = None
            try:
                async with self._tracer.span("synthèse vocale", kind="tts") as span:
                    async with contextlib.aclosing(
                        self._tts.stream(_sentences(queue, self._bus))
                    ) as chunks:
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
                stt_engine=stt_engine,
            )
        await self._bus.publish(
            "voice.turn",
            {
                "latency_ms": report.latency_ms,
                "stt_ms": report.stt_ms,
                "speculative": report.speculative,
                "first_token_ms": report.first_token_ms,
                "tts_engine": report.tts_engine,
                "stt_engine": report.stt_engine,
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
