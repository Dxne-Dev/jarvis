"""L'écoute du pipeline vocal : le mot de réveil (et sa vérification), l'écoute d'une phrase
jusqu'à sa fin, la transcription en ligne au fil de la parole, et la coupure de Jarvis
quand on lui parle pendant qu'il répond.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import numpy as np

from ojarvis.core.logs import get_logger
from ojarvis.voice.audio import FRAME_S, FRAME_SAMPLES, Frame, Pcm
from ojarvis.voice.parts import VoiceParts
from ojarvis.voice.states import VoiceState
from ojarvis.voice.stt import Transcript
from ojarvis.voice.stt_online import SttStream
from ojarvis.voice.vad import Endpoint
from ojarvis.voice.wake import mentions_jarvis

log = get_logger(__name__)


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
    speculative_engine: str = "whisper"
    follow_up: bool = False
    #: Déjà relancé une fois après une transcription vide (« Hey Jarvis » … silence).
    retried: bool = False
    #: Transcription en ligne : l'audio y part pendant la phrase.
    stream: SttStream | None = None
    #: Trames retenues pendant une courte pause (envoyées si la parole reprend).
    held: list[Frame] = field(default_factory=list)


class Listening(VoiceParts):
    """L'écoute : réveil, phrase, coupure (mélangée à `VoicePipeline`)."""

    def _wake_step(self, frame: Frame) -> None:
        if self._wake is None:
            # Pas de mot de réveil : le détecteur de parole apprend le bruit de la pièce.
            self._vad.process(frame.pcm)
            return
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
        if self._wake is not None:
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
        self._stream_step(listening, frame, event)
        if event == Endpoint.PAUSE and listening.stream is None:
            # Transcription anticipée dès la courte pause : en ligne (Groq) si possible.
            audio = self._utterance_audio(listening)
            cloud = self.cloud_stt
            engine = cloud if cloud is not None and cloud.available else self._stt
            listening.speculative_engine = getattr(engine, "name", "whisper")
            listening.speculative = asyncio.create_task(engine.transcribe(audio))
            listening.speculative_frames = len(listening.frames)
        elif event == Endpoint.RESUME and listening.speculative is not None:
            listening.speculative.cancel()
            listening.speculative = None
        elif event == Endpoint.END:
            self._finish_listening(listening)
        elif event == Endpoint.TIMEOUT:
            if listening.speculative is not None:
                listening.speculative.cancel()
            if listening.stream is not None:
                self._spawn(listening.stream.cancel())
            self._listening = None
            if not listening.follow_up:
                self._spawn(self._bus.publish("voice.timeout", {}, persist=False))
            self._end_dictation("")  # rien entendu : le terminal le dit
            self._go_idle()

    def _stream_step(self, listening: _Listening, frame: Frame, event: Endpoint) -> None:
        """Envoie la phrase à la transcription en ligne, au fil de la parole.

        Rien ne part avant que l'on parle vraiment (après « Hey Jarvis » ou le bouton micro).
        Dès une courte pause, on demande le texte ; si la parole reprend, on continue.
        """
        engine = self.streaming_stt
        if engine is None or not self._endpointer.speaking:
            return
        if self.cloud_stt is not None and self.cloud_stt.available:
            return  # Groq passe en premier ; Cartesia ne sert qu'en relais
        stream = listening.stream
        if stream is None:
            if not engine.available:
                return
            try:
                stream = listening.stream = engine.open()
            except Exception:
                log.exception("stt_stream_open_failed")
                return
            audio = self._utterance_audio(listening)  # préroll compris
            for start in range(0, len(audio), FRAME_SAMPLES):
                stream.send(audio[start : start + FRAME_SAMPLES])
            return
        if event == Endpoint.PAUSE:
            stream.flush()
            listening.held = [frame]
        elif event == Endpoint.RESUME:
            for held in listening.held:
                stream.send(held.pcm)
            listening.held = []
            stream.send(frame.pcm)
        elif self._endpointer.paused or event == Endpoint.END:
            listening.held.append(frame)  # silence : gardé au cas où la parole reprenne
        else:
            stream.send(frame.pcm)

    def _utterance_audio(self, listening: _Listening, upto: int | None = None) -> Pcm:
        start = self._endpointer.speech_start_at or listening.opened_at
        first = start - self.config.preroll_s
        frames = [f for f in listening.frames[:upto] if f.at > first]
        if frames and frames[0] is listening.frames[0]:
            # La phrase a commencé tout de suite : le préroll est dans l'historique, juste
            # avant l'ouverture de l'écoute (sans lui, la première syllabe serait coupée).
            opened = frames[0].at
            frames = [f for f in self._history if first < f.at < opened] + frames
        return np.concatenate([f.pcm for f in frames]) if frames else np.zeros(0, np.int16)

    def _finish_listening(self, listening: _Listening) -> None:
        speech_end = self._endpointer.last_voice_at or listening.frames[-1].at
        audio = self._utterance_audio(listening)
        self._listening = None
        self._turn_audio = list(listening.frames)
        self._set_state(VoiceState.THINKING)
        self._turn = asyncio.create_task(
            self._run_turn(
                audio,
                listening.speculative,
                speech_end,
                retried=listening.retried,
                stream=listening.stream,
                speculative_engine=listening.speculative_engine,
            )
        )

    async def _busy_step(self, frame: Frame) -> None:
        cfg = self.config
        score = self._wake.score(frame.pcm) if self._wake is not None else 0.0
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
