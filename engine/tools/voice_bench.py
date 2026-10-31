"""Banc d'essai vocal : joue le corpus dans le vrai pipeline et mesure la latence.

    uv run python tools/voice_bench.py --only cartesia --variant en+fr

Chaque fichier passe par le vrai chemin : mot de réveil (openWakeWord), VAD, Whisper base,
modèle de langage (DeepSeek), synthèse (Cartesia, ou Piper en repli), sortie simulée en
temps réel. Le moteur tourne dans un dossier temporaire ; les clés viennent de `.env`
et ne sont jamais affichées.

La latence « vraie » va de la fin réelle de la phrase dans le fichier (connue par le
manifeste) au premier son de la réponse.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import statistics
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ojarvis.config import EngineConfig, repo_root, resolve_paths
from ojarvis.events.bus import Event
from ojarvis.security.secrets import MemoryBackend
from ojarvis.services import Services
from ojarvis.voice.audio import FileSource, MemorySink, read_wav
from ojarvis.voice.pipeline import VoicePipeline
from ojarvis.voice.states import VoiceConfig
from ojarvis.voice.stt import WhisperTranscriber
from ojarvis.voice.stt_online import CartesiaSTT, GroqTranscriber
from ojarvis.voice.tts import CartesiaTTS, FallbackTTS, PiperTTS
from ojarvis.voice.turn import TurnReport
from ojarvis.voice.vad import SileroVad
from ojarvis.voice.wake import OpenWakeWord

MODELS = Path.home() / ".cache/o-jarvis/models"


def _words(text: str) -> list[str]:
    import re  # noqa: PLC0415
    import unicodedata  # noqa: PLC0415

    folded = unicodedata.normalize("NFKD", text.lower())
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]+", folded)


def word_error_rate(reference: str, hypothesis: str) -> float:
    """Taux d'erreur par mot (distance d'édition sur les mots / mots de la référence)."""
    ref, hyp = _words(reference), _words(hypothesis)
    row = list(range(len(hyp) + 1))
    for i, ref_word in enumerate(ref, 1):
        previous, row[0] = row[0], i
        for j, hyp_word in enumerate(hyp, 1):
            previous, row[j] = (
                row[j],
                min(row[j] + 1, row[j - 1] + 1, previous + (ref_word != hyp_word)),
            )
    return row[len(hyp)] / max(1, len(ref))


def degrade(audio: Any) -> Any:
    """Micro faible et bruité, comme un micro intégré réglé trop bas (-30 dB + souffle)."""
    import numpy as np  # noqa: PLC0415

    rng = np.random.default_rng(5)
    quiet = audio.astype(np.float32) * 10 ** (-30 / 20) + rng.normal(0, 60, len(audio))
    return np.clip(quiet, -32768, 32767).astype(np.int16)


@dataclass
class Result:
    file: str
    engine: str
    voice: str
    variant: str
    woke: bool
    verified: bool
    report: TurnReport | None
    true_latency_ms: float | None
    wer: float | None = None


async def run_sample(
    services: Services,
    parts: dict[str, Any],
    sample: dict[str, Any],
    corpus: Path,
    *,
    degraded: bool = False,
) -> Result:
    audio = read_wav(corpus / sample["file"])
    source = FileSource(degrade(audio) if degraded else audio, realtime=True)
    sink = MemorySink(realtime=True)
    finished = asyncio.Event()
    wake: dict[str, Any] = {}

    async def on_wake(event: Event) -> None:
        wake.update(event.payload)

    subscription = services.bus.subscribe("voice.wake", on_wake)
    pipeline = VoicePipeline(
        source=source,
        sink=sink,
        wake=parts["wake"],
        vad=parts["vad"],
        stt=parts["stt"],
        tts=parts["tts"],
        chat=services.chat,
        bus=services.bus,
        tracer=services.tracer,
        config=VoiceConfig(follow_up_s=0, barge_in=False),
        on_turn=lambda _report: finished.set(),
        streaming_stt=parts.get("streaming_stt"),
        cloud_stt=parts.get("cloud_stt"),
    )
    parts["wake"].reset()
    started = time.monotonic()
    task = asyncio.create_task(pipeline.run())
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(finished.wait(), timeout=sample["speech_end_s"] + 20)
    await source.close()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    subscription.close()
    report = pipeline.last_report
    true_latency = None
    if report is not None and sink.first_audio_at is not None:
        true_latency = round((sink.first_audio_at - (started + sample["speech_end_s"])) * 1000)
    error = word_error_rate(sample["question"], report.text) if report else None
    return Result(
        sample["file"],
        sample["engine"],
        sample["voice"],
        sample["variant"],
        bool(wake),
        bool(wake.get("verified")),
        report,
        true_latency,
        error,
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", type=Path, default=Path.home() / ".cache/o-jarvis/voice-corpus")
    parser.add_argument("--only", default="", help="moteurs de synthèse du corpus, ex. cartesia")
    parser.add_argument("--variant", default="", help="variante, ex. en+fr")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--tts", default="auto", choices=["auto", "piper"])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--stt", default="groq", choices=["groq", "cartesia", "local"])
    parser.add_argument("--degrade", action="store_true", help="micro faible et bruité")
    parser.add_argument("--events", action="store_true", help="affiche les événements voice.*")
    args = parser.parse_args()

    corpus: Path = args.corpus
    samples = [s for s in json.loads((corpus / "corpus.json").read_text()) if s["positive"]]
    if args.only:
        samples = [s for s in samples if s["engine"] in args.only.split(",")]
    if args.variant:
        samples = [s for s in samples if s["variant"] in args.variant.split(",")]
    if args.limit:
        samples = samples[: args.limit]

    home = Path(tempfile.mkdtemp(prefix="ojarvis-voix-", dir=os.environ.get("TMPDIR")))
    (home / "cache").mkdir(parents=True)
    (home / "cache" / "models").symlink_to(MODELS)
    root = repo_root()
    config = EngineConfig(
        paths=resolve_paths({"OJARVIS_HOME": str(home)}),
        dev_mode=True,
        dotenv_path=root / ".env" if root else None,
    )
    services = await Services.start(config, secret_backend=MemoryBackend(), discover=False)
    await services._warm_up()
    stt = WhisperTranscriber(MODELS / "faster-whisper-base")
    await asyncio.to_thread(stt.load)
    piper = PiperTTS(MODELS / "piper")
    cartesia = CartesiaTTS(lambda: services.secrets.get("CARTESIA_API_KEY"))
    tts = FallbackTTS(cartesia, piper, prefer_secondary=lambda: args.tts == "piper")
    await piper.warm_up()
    await tts.warm_up()
    parts = {
        "wake": OpenWakeWord(MODELS / "openwakeword"),
        "vad": SileroVad(),
        "stt": stt,
        "tts": tts,
    }
    if args.stt in ("groq", "cartesia"):
        parts["streaming_stt"] = CartesiaSTT(lambda: services.secrets.get("CARTESIA_API_KEY"))
    if args.stt == "groq":
        parts["cloud_stt"] = GroqTranscriber(
            lambda: services.secrets.get("GROQ_API_KEY"), services.http
        )
    results: list[Result] = []
    if args.events:
        origin = time.monotonic()

        async def show(event: Event) -> None:
            if event.type != "voice.level":
                elapsed = time.monotonic() - origin
                print(f"  {elapsed:7.2f} {event.type} {event.payload}", flush=True)

        services.bus.subscribe("voice.*", show)
    try:
        for _ in range(args.repeat):
            for sample in samples:
                result = await run_sample(services, parts, sample, corpus, degraded=args.degrade)
                results.append(result)
                r = result.report
                print(
                    f"{result.engine:8} {result.voice[:16]:16} {result.variant:6} "
                    f"réveil={'oui' if result.woke else 'non'}"
                    f"{' (vérifié)' if result.verified else ''} "
                    + (
                        f"latence={r.latency_ms} ms vraie={result.true_latency_ms} ms "
                        f"stt={r.stt_engine} {r.stt_ms} ms{'*' if r.speculative else ''} "
                        f"erreurs={result.wer:.0%} "
                        f"jeton={r.first_token_ms} voix={r.tts_engine} | {r.text!r} → "
                        f"{r.reply[:70]!r}"
                        if r
                        else "pas de réponse"
                    ),
                    flush=True,
                )
    finally:
        await tts.close()
        await services.stop()

    answered = [r for r in results if r.report and r.true_latency_ms is not None]
    woke = sum(r.woke for r in results)
    print(f"\nréveil : {woke}/{len(results)} ; réponses parlées : {len(answered)}/{len(results)}")
    if answered:
        latencies = [r.true_latency_ms for r in answered if r.true_latency_ms is not None]
        stt_ms = [r.report.stt_ms for r in answered if r.report]
        errors = [r.wer for r in answered if r.wer is not None]
        print(
            f"latence vraie : médiane {statistics.median(latencies):.0f} ms, "
            f"min {min(latencies):.0f}, max {max(latencies):.0f} ; "
            f"transcription médiane {statistics.median(stt_ms):.0f} ms ; "
            f"erreurs de mots moyennes {statistics.mean(errors):.0%}"
        )


if __name__ == "__main__":
    asyncio.run(main())
