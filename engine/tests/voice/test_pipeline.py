"""Pipeline vocal avec des composants simulés et une horloge virtuelle (aucune attente réelle)."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from ojarvis.events.bus import Event, EventBus
from ojarvis.voice.audio import FileSource, MemorySink, Pcm, VirtualClock
from ojarvis.voice.pipeline import VoicePipeline
from ojarvis.voice.states import SPOKEN_LLM_ERROR, SPOKEN_STT_ERROR, VoiceConfig, VoiceState
from ojarvis.voice.stt import SttError, Transcript
from ojarvis.voice.vad import EndpointConfig, EnergyVad, SpeechDetector
from tests.voice.fakes import (
    FakeChat,
    FakeCloudSTT,
    FakeStreamingSTT,
    FakeSTT,
    FakeTracer,
    FakeTTS,
    FakeVad,
    FakeWake,
    build_audio,
    wait_until,
)


def config(**changes: Any) -> VoiceConfig:
    base: dict[str, Any] = {
        "follow_up_s": 0.0,
        "endpoint": EndpointConfig(
            hangover_s=0.4, pause_s=0.16, min_speech_s=0.16, no_speech_timeout_s=2.0
        ),
    }
    base.update(changes)
    return VoiceConfig(**base)


@dataclass
class Rig:
    pipeline: VoicePipeline
    source: FileSource
    sink: MemorySink
    stt: FakeSTT
    tts: FakeTTS
    chat: FakeChat
    wake: FakeWake
    tracer: FakeTracer
    events: list[Event] = field(default_factory=list)

    def types(self) -> list[str]:
        return [e.type for e in self.events if e.type != "voice.level"]

    def states(self) -> list[str]:
        return [e.payload["state"] for e in self.events if e.type == "voice.state"]


@contextlib.asynccontextmanager
async def rig(
    audio: Pcm,
    *,
    stt: FakeSTT | None = None,
    chat: FakeChat | None = None,
    tts: FakeTTS | None = None,
    wake: FakeWake | None = None,
    streaming: FakeStreamingSTT | None = None,
    cloud: FakeCloudSTT | None = None,
    vad: SpeechDetector | None = None,
    wake_word: bool = True,
    **changes: Any,
) -> AsyncIterator[Rig]:
    clock = VirtualClock()
    bus = EventBus()
    source = FileSource(audio, clock=clock)
    sink = MemorySink(clock=clock)
    parts = Rig(
        pipeline=None,  # type: ignore[arg-type]
        source=source,
        sink=sink,
        stt=stt or FakeSTT(),
        tts=tts or FakeTTS(),
        chat=chat or FakeChat(),
        wake=wake or FakeWake(),
        tracer=FakeTracer(),
    )

    async def collect(event: Event) -> None:
        parts.events.append(event)

    bus.subscribe("voice.*", collect)
    parts.pipeline = VoicePipeline(
        source=source,
        sink=sink,
        wake=parts.wake if wake_word else None,
        vad=vad or FakeVad(),
        stt=parts.stt,
        tts=parts.tts,
        chat=parts.chat,  # type: ignore[arg-type]
        bus=bus,
        tracer=parts.tracer,  # type: ignore[arg-type]
        config=config(**changes),
        clock=clock,
        streaming_stt=streaming,
        cloud_stt=cloud,
    )
    task = asyncio.create_task(parts.pipeline.run())
    try:
        yield parts
    finally:
        await source.close()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await bus.drain()


async def test_hey_jarvis_then_a_question_gets_a_spoken_answer() -> None:
    audio = build_audio(("silence", 0.5), ("wake", 0.8), ("speech", 1.2))
    async with rig(audio) as r:
        await wait_until(lambda: r.pipeline.last_report is not None)
        # L'événement « veille » est publié par une tâche : on l'attend lui aussi.
        await wait_until(lambda: r.states()[-1:] == ["idle"])
        report = r.pipeline.last_report
        assert report is not None
        assert report.text == "quelle heure est-il ?"
        assert report.reply == "Il est dix heures. Autre chose ?"
        assert r.tts.sentences == ["Il est dix heures.", "Autre chose ?"]
        assert r.chat.calls[0]["channel"] == "voice"
        # La latence compte le silence d'attente (0,4 s) après la dernière syllabe.
        assert report.latency_ms is not None
        assert report.latency_ms >= 400
        assert r.sink.audio_s() == pytest.approx(2.0)
        assert r.states() == ["listening", "thinking", "speaking", "idle"]
        assert "voice.wake" in r.types()
        assert "voice.turn" in r.types()
        assert r.tracer.spans == ["transcription", "synthèse vocale"]
        captions = [e.payload["text"] for e in r.events if e.type == "voice.sentence"]
        assert captions == ["Il est dix heures.", "Autre chose ?"]
        assert r.tts.warmups == 1  # connexion ouverte dès le mot de réveil


async def test_a_short_pause_starts_the_transcription_early() -> None:
    audio = build_audio(("silence", 0.5), ("wake", 0.8), ("speech", 1.2))
    async with rig(audio) as r:
        await wait_until(lambda: r.pipeline.last_report is not None)
        report = r.pipeline.last_report
        assert report is not None
        assert report.speculative is True
        assert len(r.stt.calls) == 1


async def test_speech_that_resumes_after_a_pause_is_transcribed_whole() -> None:
    audio = build_audio(
        ("silence", 0.5), ("wake", 0.8), ("speech", 0.8), ("silence", 0.24), ("speech", 0.8)
    )
    async with rig(audio) as r:
        await wait_until(lambda: r.pipeline.last_report is not None)
        report = r.pipeline.last_report
        assert report is not None
        assert len(r.stt.calls) == 2  # la transcription anticipée est jetée
        assert r.stt.calls[-1] > r.stt.calls[0]
        assert report.speculative is True


async def test_speaking_over_jarvis_interrupts_him() -> None:
    audio = build_audio(
        ("silence", 0.5), ("wake", 0.8), ("speech", 1.0), ("silence", 1.6), ("speech", 0.8)
    )
    stt = FakeSTT(["Hey Jarvis, raconte une longue histoire", "attends, stop"])
    async with rig(audio, stt=stt, tts=FakeTTS(seconds_per_sentence=6.0)) as r:
        await wait_until(lambda: len(r.chat.calls) == 2)
        assert r.sink.stopped >= 1
        interrupted = [e.payload["by"] for e in r.events if e.type == "voice.interrupted"]
        assert interrupted == ["voix"]
        assert r.chat.calls[1]["text"] == "attends, stop"


async def test_without_barge_in_only_hey_jarvis_interrupts() -> None:
    audio = build_audio(
        ("silence", 0.5), ("wake", 0.8), ("speech", 1.0), ("silence", 1.6), ("speech", 0.8)
    )
    async with rig(audio, tts=FakeTTS(seconds_per_sentence=6.0), barge_in=False) as r:
        await wait_until(lambda: r.pipeline.last_report is not None, limit=10)
        assert r.sink.stopped == 0
        assert len(r.chat.calls) == 1


async def test_hey_jarvis_interrupts_a_slow_answer() -> None:
    audio = build_audio(
        ("silence", 0.5), ("wake", 0.8), ("speech", 1.0), ("silence", 1.5), ("wake", 0.8)
    )
    async with rig(audio, chat=FakeChat(hang=True)) as r:
        await wait_until(lambda: "voice.interrupted" in r.types())
        interrupted = [e.payload["by"] for e in r.events if e.type == "voice.interrupted"]
        assert interrupted == ["mot de réveil"]
        # Après la coupure, Jarvis réécoute (l'horloge virtuelle a pu aller plus loin depuis).
        states = r.states()
        assert states[: states.index("thinking") + 2] == ["listening", "thinking", "listening"]


async def test_hey_jarvis_alone_waits_for_the_question_then_sleeps() -> None:
    audio = build_audio(("silence", 0.5), ("wake", 0.8), ("silence", 6.0))
    async with rig(audio, stt=FakeSTT(["Hey Jarvis."])) as r:
        await wait_until(lambda: "voice.timeout" in r.types(), limit=10)
        assert r.chat.calls == []
        assert r.pipeline.state == VoiceState.IDLE


async def test_an_unreachable_model_is_said_out_loud() -> None:
    audio = build_audio(("silence", 0.5), ("wake", 0.8), ("speech", 1.0))
    async with rig(audio, chat=FakeChat(error=True)) as r:
        await wait_until(lambda: r.pipeline.last_report is not None)
        assert r.tts.sentences == [SPOKEN_LLM_ERROR]


async def test_push_to_talk_needs_no_wake_word() -> None:
    audio = build_audio(("silence", 0.5), ("speech", 1.0))
    async with rig(audio, stt=FakeSTT(["Quelle heure est-il ?"])) as r:
        r.pipeline.listen_now()
        await wait_until(lambda: r.pipeline.last_report is not None)
        report = r.pipeline.last_report
        assert report is not None
        assert report.text == "Quelle heure est-il ?"
        assert "voice.wake" not in r.types()


async def test_a_hesitant_wake_word_is_checked_by_transcription() -> None:
    audio = build_audio(("silence", 0.5), ("wake", 0.8), ("silence", 0.4), ("speech", 1.0))
    stt = FakeSTT(["Et Jarvi,", "quelle heure est-il ?"])
    async with rig(audio, stt=stt, wake=FakeWake(score=0.3)) as r:
        await wait_until(lambda: r.pipeline.last_report is not None)
        wakes = [e.payload for e in r.events if e.type == "voice.wake"]
        assert wakes == [{"score": 0.3, "verified": True}]


async def test_a_hesitant_score_without_jarvis_is_ignored() -> None:
    audio = build_audio(("silence", 0.5), ("wake", 0.8), ("silence", 2.0))
    async with rig(audio, stt=FakeSTT(["Il va pleuvoir."]), wake=FakeWake(score=0.3)) as r:
        await wait_until(lambda: len(r.stt.calls) >= 1)
        await asyncio.sleep(0.05)
        assert "voice.wake" not in r.types()
        assert r.pipeline.state == VoiceState.IDLE


async def test_follow_up_continues_the_same_conversation_without_wake_word() -> None:
    audio = build_audio(
        ("silence", 0.5), ("wake", 0.8), ("speech", 1.0), ("silence", 2.6), ("speech", 1.0)
    )
    stt = FakeSTT(["Hey Jarvis, quelle heure est-il ?", "Et demain ?"])
    async with rig(audio, stt=stt, follow_up_s=3.0) as r:
        await wait_until(lambda: len(r.chat.calls) == 2)
        assert r.chat.calls[1]["text"] == "Et demain ?"
        assert r.chat.calls[1]["conversation_id"] == "conv-1"


async def test_interrupt_from_the_interface_goes_back_to_sleep() -> None:
    audio = build_audio(("silence", 0.5), ("wake", 0.8), ("speech", 1.0))
    async with rig(audio, tts=FakeTTS(seconds_per_sentence=6.0)) as r:
        await wait_until(lambda: r.pipeline.state == VoiceState.SPEAKING)
        await r.pipeline.interrupt(by="ui")
        assert r.pipeline.state == VoiceState.IDLE
        assert r.sink.stopped >= 1


async def test_a_doubtful_transcript_is_answered_but_not_learned() -> None:
    audio = build_audio(("silence", 0.5), ("wake", 0.8), ("speech", 1.0))
    async with rig(audio, stt=FakeSTT(["Kélela Kapita, Bbena"], logprob=-1.1)) as r:
        await wait_until(lambda: r.pipeline.last_report is not None)
        assert r.chat.calls[0]["learn"] is False
        assert r.tts.sentences  # Jarvis répond quand même (et peut demander de répéter)


async def test_a_clear_transcript_can_be_learned() -> None:
    audio = build_audio(("silence", 0.5), ("wake", 0.8), ("speech", 1.0))
    async with rig(audio) as r:
        await wait_until(lambda: r.pipeline.last_report is not None)
        assert r.chat.calls[0]["learn"] is True


async def test_online_transcription_receives_the_sentence_while_it_is_spoken() -> None:
    audio = build_audio(("silence", 0.5), ("wake", 0.8), ("speech", 1.2))
    streaming = FakeStreamingSTT()
    async with rig(audio, streaming=streaming) as r:
        await wait_until(lambda: r.pipeline.last_report is not None)
        report = r.pipeline.last_report
        assert report is not None
        assert report.stt_engine == "cartesia"
        assert report.text == "quelle heure est-il ?"
        assert r.stt.calls == []  # Whisper local n'a pas servi
        stream = streaming.streams[0]
        assert stream.samples / 16_000 > 1.2  # toute la phrase, préroll compris
        assert stream.flushes >= 1  # texte demandé dès la courte pause
        assert stream.cancelled  # connexion refermée après la phrase


async def test_nothing_is_sent_online_when_nobody_speaks() -> None:
    streaming = FakeStreamingSTT()
    async with rig(build_audio(("silence", 4.0)), streaming=streaming) as r:
        r.pipeline.listen_now()
        await wait_until(lambda: "voice.timeout" in r.types(), limit=10)
        assert streaming.streams == []


async def test_a_failing_online_transcription_falls_back_to_whisper() -> None:
    audio = build_audio(("silence", 0.5), ("wake", 0.8), ("speech", 1.0))
    async with rig(audio, streaming=FakeStreamingSTT(fail=True)) as r:
        await wait_until(lambda: r.pipeline.last_report is not None)
        report = r.pipeline.last_report
        assert report is not None
        assert report.stt_engine == "whisper"
        assert len(r.stt.calls) == 1
        await wait_until(lambda: "voice.stt_fallback" in r.types())


async def test_the_start_of_a_sentence_said_right_after_the_wake_word_is_kept() -> None:
    audio = build_audio(("silence", 0.5), ("wake", 0.8), ("speech", 1.2))
    async with rig(audio) as r:
        await wait_until(lambda: r.pipeline.last_report is not None)
        # Marqueur restant (0,72 s) + phrase (1,2 s) + pause (0,16 s) + préroll (0,35 s).
        assert r.stt.calls[0] >= 2.3


async def test_groq_transcribes_the_sentence_as_soon_as_it_pauses() -> None:
    audio = build_audio(("silence", 0.5), ("wake", 0.8), ("speech", 1.2))
    cloud = FakeCloudSTT()
    streaming = FakeStreamingSTT()
    async with rig(audio, cloud=cloud, streaming=streaming) as r:
        await wait_until(lambda: r.pipeline.last_report is not None)
        report = r.pipeline.last_report
        assert report is not None
        assert report.stt_engine == "groq"
        assert report.speculative is True  # envoyée dès la pause
        assert len(cloud.calls) == 1
        assert r.stt.calls == []
        assert streaming.streams == []  # Cartesia ne sert qu'en relais


async def test_without_groq_key_cartesia_takes_over() -> None:
    audio = build_audio(("silence", 0.5), ("wake", 0.8), ("speech", 1.0))
    streaming = FakeStreamingSTT()
    async with rig(audio, cloud=FakeCloudSTT(has_key=False), streaming=streaming) as r:
        await wait_until(lambda: r.pipeline.last_report is not None)
        report = r.pipeline.last_report
        assert report is not None
        assert report.stt_engine == "cartesia"
        assert len(streaming.streams) == 1


async def test_a_failing_groq_falls_back_to_local_whisper() -> None:
    audio = build_audio(("silence", 0.5), ("wake", 0.8), ("speech", 1.0))
    async with rig(audio, cloud=FakeCloudSTT(fail=True)) as r:
        await wait_until(lambda: r.pipeline.last_report is not None)
        report = r.pipeline.last_report
        assert report is not None
        assert report.stt_engine == "whisper"
        assert len(r.stt.calls) == 1
        await wait_until(lambda: "voice.stt_fallback" in r.types())


async def test_when_groq_fails_the_recorded_sentence_goes_to_cartesia() -> None:
    audio = build_audio(("silence", 0.5), ("wake", 0.8), ("speech", 1.0))
    streaming = FakeStreamingSTT(text="Quelle heure est-il ?")
    async with rig(audio, cloud=FakeCloudSTT(fail=True), streaming=streaming) as r:
        await wait_until(lambda: r.pipeline.last_report is not None)
        report = r.pipeline.last_report
        assert report is not None
        assert report.stt_engine == "cartesia"
        assert r.stt.calls == []  # Whisper local n'a pas servi
        assert streaming.streams[0].samples > 16_000  # la phrase entière, d'un bloc


async def test_jarvis_can_say_a_text_on_his_own_when_idle() -> None:
    audio = build_audio(("silence", 3.0))
    async with rig(audio) as r:
        await wait_until(lambda: r.pipeline.frames_seen > 2)
        assert r.pipeline.say("Bonjour Octave. Voici ta journée.")
        assert not r.pipeline.say("Pas deux à la fois.")
        await wait_until(lambda: r.states()[-1:] == ["idle"] and "speaking" in r.states())
        assert r.tts.sentences == ["Bonjour Octave.", "Voici ta journée."]
        captions = [e.payload["text"] for e in r.events if e.type == "voice.sentence"]
        assert captions == ["Bonjour Octave.", "Voici ta journée."]
        assert r.chat.calls == []  # rien n'est demandé au modèle
        assert not r.pipeline.say("   ")


async def test_what_he_says_on_his_own_can_be_interrupted() -> None:
    audio = build_audio(("silence", 20.0))
    async with rig(audio, tts=FakeTTS(seconds_per_sentence=6.0)) as r:
        await wait_until(lambda: r.pipeline.frames_seen > 1)
        assert r.pipeline.say("Un très long briefing. Avec beaucoup de phrases.")
        await wait_until(lambda: "speaking" in r.states())
        await r.pipeline.interrupt(by="interface")
        await wait_until(lambda: "voice.interrupted" in r.types())
        assert [e.payload["by"] for e in r.events if e.type == "voice.interrupted"] == ["interface"]
        assert r.sink.stopped >= 1


# ------------------------------------------------------------------ dictée du terminal (#10)


async def test_the_terminal_gets_the_sentence_instead_of_a_spoken_answer() -> None:
    audio = build_audio(("silence", 0.5), ("speech", 1.0), ("silence", 1.0))
    async with rig(audio, stt=FakeSTT(["Liste les fichiers du dossier."])) as r:
        heard = r.pipeline.dictate()
        await wait_until(heard.done)
        assert heard.result() == "Liste les fichiers du dossier."
        assert r.chat.calls == []  # pas de tour vocal : le terminal s'en charge
        assert r.tts.sentences == []  # rien de dit à voix haute
        assert "voice.wake" not in r.types()  # comme le bouton micro


async def test_a_silent_dictation_sends_nothing_online_and_says_so() -> None:
    streaming = FakeStreamingSTT()
    async with rig(build_audio(("silence", 4.0)), streaming=streaming) as r:
        heard = r.pipeline.dictate()
        await wait_until(heard.done, limit=10)
        assert heard.result() == ""
        assert streaming.streams == []  # rien n'est parti en ligne


async def test_one_dictation_at_a_time() -> None:
    audio = build_audio(("silence", 0.5), ("speech", 1.0), ("silence", 1.0))
    async with rig(audio, stt=FakeSTT(["Une seule phrase."])) as r:
        first, second = r.pipeline.dictate(), r.pipeline.dictate()
        assert first is second
        await wait_until(first.done)
        assert first.result() == "Une seule phrase."


# ---------------------------------------------------------------- profil « Tout Meta »


class MuseVoiceDown(FakeSTT):
    """Muse Voice Transcribe injoignable : le seul moteur du profil « Tout Meta »."""

    name = "meta"

    async def transcribe(self, audio: Pcm) -> Transcript:
        self.calls.append(len(audio) / 16_000)
        raise SttError("Meta injoignable : ConnectError")


async def test_without_a_wake_word_speech_alone_opens_nothing() -> None:
    audio = build_audio(("silence", 0.5), ("wake", 0.8), ("speech", 1.0), ("silence", 0.5))
    async with rig(audio, vad=EnergyVad(), wake_word=False) as r:
        await wait_until(lambda: r.pipeline.frames_seen >= len(audio) // 1280)
        assert r.stt.calls == []  # rien n'a quitté la machine
        assert r.chat.calls == []
        assert r.pipeline.state == VoiceState.IDLE


async def test_the_shortcut_then_a_sentence_heard_by_its_volume_gets_an_answer() -> None:
    audio = build_audio(("silence", 1.0), ("speech", 1.0), ("silence", 1.0))
    stt = FakeSTT(["Quelle heure est-il ?"])
    async with rig(audio, stt=stt, vad=EnergyVad(), wake_word=False) as r:
        r.pipeline.listen_now()
        await wait_until(lambda: r.pipeline.last_report is not None)
        report = r.pipeline.last_report
        assert report is not None
        assert report.text == "Quelle heure est-il ?"
        assert stt.calls[-1] == pytest.approx(1.0, abs=0.6)  # la phrase, pas le silence


async def test_a_failed_transcription_is_said_out_loud_without_another_engine() -> None:
    audio = build_audio(("silence", 0.5), ("speech", 1.0), ("silence", 1.0))
    async with rig(audio, stt=MuseVoiceDown(), wake_word=False) as r:
        r.pipeline.listen_now()
        await wait_until(lambda: " ".join(r.tts.sentences) == SPOKEN_STT_ERROR)
        await wait_until(lambda: r.pipeline.state == VoiceState.IDLE)
        assert r.chat.calls == []
        assert "voice.error" in r.types()
