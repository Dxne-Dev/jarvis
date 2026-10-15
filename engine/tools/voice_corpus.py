"""Fabrique un corpus audio de test : « Hey Jarvis, … » dit par plusieurs voix de synthèse.

Chaque fichier est un WAV 16 kHz mono 16 bits : un silence, la phrase, puis un silence.
Le manifeste `corpus.json` décrit chaque fichier (voix, texte, présence du mot de réveil).

    uv run python tools/voice_corpus.py --out ~/.cache/o-jarvis/voice-corpus

Voix utilisées : Piper (local), espeak-ng (local) et Cartesia (si CARTESIA_API_KEY est
défini dans l'environnement). La clé n'est jamais écrite ni affichée.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import time
import wave
from collections.abc import Callable
from dataclasses import asdict, dataclass
from math import gcd
from pathlib import Path

import httpx
import numpy as np
import numpy.typing as npt
from scipy.signal import resample_poly

RATE = 16_000
Pcm = npt.NDArray[np.int16]

QUESTIONS = [
    "quelle heure est-il ?",
    "donne-moi une idée de dîner rapide.",
    "combien font douze fois huit ?",
    "rappelle-moi ce que je bois le matin.",
    "explique-moi ce qu'est un trou noir en une phrase.",
    "quelle est la capitale du Bénin ?",
]
NEGATIVES = [
    "Bonjour, comment ça va aujourd'hui ?",
    "Je pense qu'il va pleuvoir ce soir.",
    "Passe-moi le sel, s'il te plaît.",
    "Le train part à huit heures et quart.",
]

PIPER_VOICES: list[tuple[str, int | None]] = [
    ("fr_FR-tom-medium", None),
    ("fr_FR-siwis-medium", None),
    ("fr_FR-upmc-medium", 0),
    ("fr_FR-upmc-medium", 1),
    ("fr_FR-gilles-low", None),
    ("fr_FR-mls-medium", 2),
    ("fr_FR-mls-medium", 7),
]
ESPEAK_VOICES = ["fr", "fr+f3", "fr+m3", "fr-be"]
ESPEAK_EN_VOICES = [
    ("en-us", "fr"),
    ("en", "fr+m3"),
    ("en-us+m3", "fr-be"),
    ("en+f3", "fr+f3"),
    ("en-us+m7", "fr"),
]
CARTESIA_VOICES = {
    "Étienne": "c6ccfe32-6bee-484a-a8a2-7a51bee93f99",
    "Inès": "7c58f4a4-a72c-42fa-a503-41b9408820f3",
    "Mathis": "996ec149-0dca-4389-ad08-e2d6f906b4bf",
    "Jade": "92579402-6868-412e-b845-3efed0be7a9e",
    "Henri": "d9f4af15-c402-4f50-bbda-d8823d028d6a",
    "Zoé": "b56a7171-86f0-42b6-b3fa-a316794aa4e0",
}
CARTESIA_VERSION = "2026-08-14"


@dataclass
class Sample:
    file: str
    engine: str
    voice: str
    text: str
    question: str
    positive: bool
    variant: str
    speech_end_s: float


def resample(audio: npt.NDArray[np.int16], rate: int) -> Pcm:
    if rate == RATE:
        return audio
    factor = gcd(RATE, rate)
    out = resample_poly(audio.astype(np.float32), RATE // factor, rate // factor)
    result: Pcm = np.clip(out, -32768, 32767).astype(np.int16)
    return result


def frame(speech: Pcm, *, lead_s: float = 0.8, tail_s: float = 1.6) -> tuple[Pcm, float]:
    """Ajoute du silence (avec un léger bruit de fond) avant et après la phrase."""
    rng = np.random.default_rng(len(speech))
    lead = (rng.normal(0, 12, int(lead_s * RATE))).astype(np.int16)
    tail = (rng.normal(0, 12, int(tail_s * RATE))).astype(np.int16)
    return np.concatenate([lead, speech, tail]), (len(lead) + len(speech)) / RATE


def write_wav(path: Path, audio: Pcm) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(audio.tobytes())


def trim(audio: Pcm, threshold: int = 300) -> Pcm:
    """Retire les silences du début et de la fin produits par le moteur de synthèse."""
    loud = np.flatnonzero(np.abs(audio.astype(np.int32)) > threshold)
    if loud.size == 0:
        return audio
    return audio[max(loud[0] - 160, 0) : loud[-1] + 160]


def piper_synth(models: Path) -> Callable[[str, str], Pcm]:
    from piper import PiperVoice, SynthesisConfig  # noqa: PLC0415

    cache: dict[str, PiperVoice] = {}

    def synth(voice: str, text: str) -> Pcm:
        name, _, speaker = voice.partition("#")
        if name not in cache:
            cache[name] = PiperVoice.load(models / f"{name}.onnx")
        model = cache[name]
        config = SynthesisConfig(speaker_id=int(speaker) if speaker else None)
        chunks = list(model.synthesize(text, syn_config=config))
        audio = np.concatenate([c.audio_int16_array for c in chunks])
        return trim(resample(audio, chunks[0].sample_rate))

    return synth


def espeak_synth(voice: str, text: str) -> Pcm:
    with tempfile.TemporaryDirectory() as folder:
        out = Path(folder) / "e.wav"
        subprocess.run(
            ["espeak-ng", "-v", voice, "-s", "165", "-w", str(out), text],
            check=True,
            capture_output=True,
        )
        with wave.open(str(out), "rb") as handle:
            rate = handle.getframerate()
            audio = np.frombuffer(handle.readframes(handle.getnframes()), dtype=np.int16)
    return trim(resample(audio, rate))


def cartesia_synth(client: httpx.Client, key: str) -> Callable[[str, str, str], Pcm]:
    def synth(voice_id: str, text: str, language: str) -> Pcm:
        response = client.post(
            "https://api.cartesia.ai/tts/bytes",
            headers={"Authorization": f"Bearer {key}", "Cartesia-Version": CARTESIA_VERSION},
            json={
                "model_id": "sonic-3.6",
                "transcript": text,
                "voice": {"mode": "id", "id": voice_id},
                "language": language,
                "output_format": {"container": "raw", "encoding": "pcm_s16le", "sample_rate": RATE},
            },
            timeout=30.0,
        )
        response.raise_for_status()
        return trim(np.frombuffer(response.content, dtype=np.int16).copy())

    return synth


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path.home() / ".cache/o-jarvis/voice-corpus")
    parser.add_argument("--models", type=Path, default=Path.home() / ".cache/o-jarvis/models/piper")
    parser.add_argument("--engines", default="piper,espeak,cartesia")
    args = parser.parse_args()
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    engines = set(args.engines.split(","))
    samples: list[Sample] = []

    def add(
        engine: str, voice: str, speech: Pcm, *, text: str, question: str, variant: str
    ) -> None:
        audio, end = frame(speech)
        name = f"{engine}-{len(samples):03d}.wav"
        write_wav(out / name, audio)
        positive = variant != "negatif"
        samples.append(Sample(name, engine, voice, text, question, positive, variant, end))

    if "piper" in engines:
        synth = piper_synth(args.models)
        for index, (name, speaker) in enumerate(PIPER_VOICES):
            voice = name if speaker is None else f"{name}#{speaker}"
            question = QUESTIONS[index % len(QUESTIONS)]
            text = f"Hey Jarvis, {question}"
            add("piper", voice, synth(voice, text), text=text, question=question, variant="fr")
            negative = NEGATIVES[index % len(NEGATIVES)]
            add(
                "piper",
                voice,
                synth(voice, negative),
                text=negative,
                question="",
                variant="negatif",
            )

    if "espeak" in engines:
        for index, voice in enumerate(ESPEAK_VOICES):
            question = QUESTIONS[(index + 2) % len(QUESTIONS)]
            text = f"Hey Jarvis, {question}"
            add(
                "espeak",
                voice,
                espeak_synth(voice, text),
                text=text,
                question=question,
                variant="fr",
            )
        # Mot de réveil dit à l'anglaise par une voix anglaise, puis la question en français.
        for index, (wake_voice, fr_voice) in enumerate(ESPEAK_EN_VOICES):
            question = QUESTIONS[(index + 1) % len(QUESTIONS)]
            pause = np.zeros(int(0.18 * RATE), dtype=np.int16)
            speech = np.concatenate(
                [espeak_synth(wake_voice, "Hey Jarvis"), pause, espeak_synth(fr_voice, question)]
            )
            text = f"Hey Jarvis! {question}"
            add("espeak", wake_voice, speech, text=text, question=question, variant="en+fr")

    key = os.environ.get("CARTESIA_API_KEY", "")
    if "cartesia" in engines and key:
        with httpx.Client() as client:
            synth_c = cartesia_synth(client, key)
            for index, (voice, voice_id) in enumerate(CARTESIA_VOICES.items()):
                question = QUESTIONS[(index + 4) % len(QUESTIONS)]
                text = f"Hey Jarvis, {question}"
                speech = synth_c(voice_id, text, "fr")
                add("cartesia", voice, speech, text=text, question=question, variant="fr")
                # Mot de réveil dit à l'anglaise, puis la question en français.
                wake = synth_c(voice_id, "Hey Jarvis!", "en")
                pause = np.zeros(int(0.18 * RATE), dtype=np.int16)
                speech = np.concatenate([wake, pause, synth_c(voice_id, question, "fr")])
                text = f"Hey Jarvis! {question}"
                add("cartesia", voice, speech, text=text, question=question, variant="en+fr")
                time.sleep(0.2)
            negative = NEGATIVES[0]
            first = next(iter(CARTESIA_VOICES.values()))
            speech = synth_c(first, negative, "fr")
            add("cartesia", "Étienne", speech, text=negative, question="", variant="negatif")

    (out / "corpus.json").write_text(
        json.dumps([asdict(s) for s in samples], ensure_ascii=False, indent=2)
    )
    print(f"{len(samples)} fichiers dans {out}")


if __name__ == "__main__":
    main()
