"""Détection de parole (Silero VAD v6, ou le volume du son) et décision de fin de phrase.

Le modèle ONNX est celui fourni avec faster-whisper : rien à télécharger. Il travaille
sur des morceaux de 32 ms (512 échantillons à 16 kHz) précédés de 64 échantillons de contexte.
Le profil « Tout Meta » n'utilise aucun modèle qui ne soit pas de Meta : la parole y est
reconnue à son volume, au-dessus du bruit de fond de la pièce.
"""

from __future__ import annotations

import enum
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from ojarvis.voice.audio import Pcm

CHUNK = 512
CONTEXT = 64


def bundled_model() -> Path:
    import faster_whisper  # noqa: PLC0415

    return Path(faster_whisper.__file__).parent / "assets" / "silero_vad_v6.onnx"


class SpeechDetector(Protocol):
    def process(self, pcm: Pcm) -> float: ...

    def reset(self) -> None: ...


class SileroVad:
    """Probabilité de parole, trame après trame, avec l'état du réseau conservé entre les appels."""

    def __init__(self, model: Path | None = None) -> None:
        import onnxruntime as ort  # noqa: PLC0415

        options = ort.SessionOptions()
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 1
        options.log_severity_level = 4
        self._session: Any = ort.InferenceSession(
            str(model or bundled_model()), sess_options=options, providers=["CPUExecutionProvider"]
        )
        self.reset()

    def reset(self) -> None:
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._context = np.zeros(CONTEXT, dtype=np.float32)
        self._rest = np.zeros(0, dtype=np.float32)

    def process(self, pcm: Pcm) -> float:
        """Renvoie la plus forte probabilité de parole parmi les morceaux complets reçus."""
        audio = np.concatenate([self._rest, pcm.astype(np.float32) / 32768.0])
        best = 0.0
        start = 0
        while start + CHUNK <= len(audio):
            chunk = audio[start : start + CHUNK]
            window = np.concatenate([self._context, chunk])[None, :]
            out, self._h, self._c = self._session.run(
                None, {"input": window, "h": self._h, "c": self._c}
            )
            best = max(best, float(np.asarray(out).reshape(-1)[0]))
            self._context = chunk[-CONTEXT:]
            start += CHUNK
        self._rest = audio[start:]
        return best


class EnergyVad:
    """La parole reconnue à son volume : du simple calcul, pas un modèle.

    Le bruit de fond (ventilateur, rue) est le volume des trames les plus calmes des dernières
    secondes : les silences entre les mots le gardent bas pendant qu'on parle. La probabilité
    vaut 0,5 à `margin_db` au-dessus du fond, 1 à deux fois cette marge.
    """

    def __init__(
        self, *, margin_db: float = 12.0, window: int = 60, quietest_db: float = -70.0
    ) -> None:
        self.margin_db = margin_db
        self._quietest = quietest_db
        self._recent: deque[float] = deque(maxlen=window)

    @property
    def floor_db(self) -> float:
        if not self._recent:
            return self._quietest
        return max(float(np.percentile(self._recent, 10)), self._quietest)

    def reset(self) -> None:
        """Le fond de la pièce est gardé d'une phrase à l'autre : rien à remettre à zéro."""

    def process(self, pcm: Pcm) -> float:
        samples = pcm.astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(samples**2))) if samples.size else 0.0
        self._recent.append(20.0 * float(np.log10(max(rms, 1e-6))))
        above = self._recent[-1] - self.floor_db
        return min(max(above / (2 * self.margin_db), 0.0), 1.0)


class Endpoint(enum.Enum):
    NONE = "none"
    START = "start"  # la parole commence
    PAUSE = "pause"  # court silence : on peut transcrire en avance
    RESUME = "resume"  # la parole reprend après une pause
    END = "end"  # silence assez long : la phrase est finie
    TIMEOUT = "timeout"  # personne n'a parlé


@dataclass
class EndpointConfig:
    start_threshold: float = 0.5
    end_threshold: float = 0.35
    min_speech_s: float = 0.16
    pause_s: float = 0.2
    hangover_s: float = 0.6
    max_utterance_s: float = 20.0
    no_speech_timeout_s: float = 6.0


class Endpointer:
    """Machine à états : attente → parole → (pause) → fin, à partir des probabilités du VAD."""

    def __init__(self, config: EndpointConfig | None = None) -> None:
        self.config = config or EndpointConfig()
        self.reset(0.0)

    def reset(self, now: float, *, timeout_s: float | None = None) -> None:
        self.opened_at = now
        self.timeout_s = timeout_s if timeout_s is not None else self.config.no_speech_timeout_s
        self.speaking = False
        self.paused = False
        self.speech_start_at: float | None = None
        self.last_voice_at: float | None = None
        self._voiced_since: float | None = None

    def update(self, prob: float, now: float, frame_s: float) -> Endpoint:
        if not self.speaking:
            return self._waiting(prob, now, frame_s)
        return self._listening(prob, now)

    def _waiting(self, prob: float, now: float, frame_s: float) -> Endpoint:
        cfg = self.config
        if prob >= cfg.start_threshold:
            if self._voiced_since is None:
                self._voiced_since = now - frame_s
            if now - self._voiced_since >= cfg.min_speech_s:
                self.speaking = True
                self.speech_start_at = self._voiced_since
                self.last_voice_at = now
                return Endpoint.START
        else:
            self._voiced_since = None
        if now - self.opened_at >= self.timeout_s:
            return Endpoint.TIMEOUT
        return Endpoint.NONE

    def _listening(self, prob: float, now: float) -> Endpoint:
        cfg = self.config
        start = self.speech_start_at if self.speech_start_at is not None else now
        if prob >= cfg.end_threshold:
            self.last_voice_at = now
            if self.paused:
                self.paused = False
                return Endpoint.RESUME
            return Endpoint.END if now - start >= cfg.max_utterance_s else Endpoint.NONE
        silence = now - (self.last_voice_at if self.last_voice_at is not None else now)
        if silence >= cfg.hangover_s:
            return Endpoint.END
        if not self.paused and silence >= cfg.pause_s:
            self.paused = True
            return Endpoint.PAUSE
        return Endpoint.NONE
