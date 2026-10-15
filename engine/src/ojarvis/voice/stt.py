"""Transcription locale en français : faster-whisper, modèle `base`, int8 sur le CPU.

Whisper encode toujours une fenêtre de 30 s, même pour une phrase de 2 s. Ici, la fenêtre
est réduite à 10 s quand la phrase est courte : l'encodeur va environ 4 fois plus vite
(0,45 s au lieu de 1,7 s sur cette machine) pour une transcription quasi identique.
Si ce chemin rapide échoue, on revient à la méthode standard de faster-whisper.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

import anyio.to_thread
import numpy as np

from ojarvis.core.downloads import PinnedFile
from ojarvis.core.logs import get_logger
from ojarvis.voice.audio import RATE, Pcm

log = get_logger(__name__)

WHISPER_REVISION = "ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66"
WHISPER_BASE = f"https://huggingface.co/Systran/faster-whisper-base/resolve/{WHISPER_REVISION}"
WHISPER_FILES: dict[str, PinnedFile] = {
    "config.json": PinnedFile(
        f"{WHISPER_BASE}/config.json",
        "56a6d8110d311f19c8f0471e562832c7527f146b567275bfca59fcf7c184da9a",
    ),
    "model.bin": PinnedFile(
        f"{WHISPER_BASE}/model.bin",
        "d01c3014881c9c6f3133c182f3d2887eb6ca1c789a7538c5c007196857a0a6a9",
    ),
    "tokenizer.json": PinnedFile(
        f"{WHISPER_BASE}/tokenizer.json",
        "fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab",
    ),
    "vocabulary.txt": PinnedFile(
        f"{WHISPER_BASE}/vocabulary.txt",
        "34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913",
    ),
}

#: Au-delà, la fenêtre courte n'apporte plus rien : on encode la durée réelle (+ marge).
SHORT_WINDOW_S = 10
FRAMES_PER_S = 100


#: En dessous, la transcription est douteuse (mesuré sur le corpus : les phrases ratées
#: sont toutes sous -1, les bonnes au-dessus de -0,7).
RELIABLE_LOGPROB = -0.6


@dataclass(frozen=True)
class Transcript:
    text: str
    audio_s: float
    duration_ms: float
    no_speech_prob: float = 0.0
    #: Log-probabilité moyenne par jeton : la confiance de Whisper dans son texte.
    avg_logprob: float = 0.0

    @property
    def reliable(self) -> bool:
        """Assez sûre pour que Jarvis en retienne des faits (il répond dans tous les cas)."""
        return self.avg_logprob >= RELIABLE_LOGPROB and self.no_speech_prob < 0.6


class Transcriber(Protocol):
    async def transcribe(self, audio: Pcm) -> Transcript: ...


class CloudTranscriber(Transcriber, Protocol):
    """Transcription en ligne, par phrase entière (Groq)."""

    name: str

    @property
    def available(self) -> bool: ...


class WhisperTranscriber:
    def __init__(self, folder: Path, *, threads: int = 4, language: str = "fr") -> None:
        self.folder = folder
        self._threads = threads
        self._language = language
        self._model: Any = None
        self._tokenizer: Any = None
        self._prompt: list[int] = []
        self._suppress: list[int] = []
        self._lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        from faster_whisper import WhisperModel  # noqa: PLC0415
        from faster_whisper.tokenizer import Tokenizer  # noqa: PLC0415
        from faster_whisper.transcribe import get_suppressed_tokens  # noqa: PLC0415

        with self._lock:
            if self._model is not None:
                return
            model = WhisperModel(
                str(self.folder), device="cpu", compute_type="int8", cpu_threads=self._threads
            )
            tokenizer = Tokenizer(
                model.hf_tokenizer, True, task="transcribe", language=self._language
            )
            self._prompt = [
                tokenizer.sot,
                tokenizer.language,
                tokenizer.transcribe,
                tokenizer.no_timestamps,
            ]
            self._suppress = list(get_suppressed_tokens(tokenizer, (-1,)) or [])
            self._tokenizer = tokenizer
            self._model = model

    async def transcribe(self, audio: Pcm) -> Transcript:
        return await anyio.to_thread.run_sync(self.transcribe_sync, audio)

    def transcribe_sync(self, audio: Pcm) -> Transcript:
        self.load()
        start = time.perf_counter()
        samples = audio.astype(np.float32) / 32768.0
        seconds = len(samples) / RATE
        with self._lock:
            try:
                text, no_speech, logprob = self._fast(samples, seconds)
            except Exception:
                log.exception("whisper_fast_path_failed")
                text, no_speech, logprob = self._standard(samples)
        return Transcript(
            text=text.strip(),
            audio_s=round(seconds, 2),
            duration_ms=round((time.perf_counter() - start) * 1000, 1),
            no_speech_prob=round(no_speech, 3),
            avg_logprob=round(logprob, 3),
        )

    def _fast(self, samples: Any, seconds: float) -> tuple[str, float, float]:
        import ctranslate2  # noqa: PLC0415

        short = seconds <= SHORT_WINDOW_S - 2
        window_s = SHORT_WINDOW_S if short else min(30, math.ceil(seconds) + 2)
        padded = np.zeros(window_s * RATE, dtype=np.float32)
        padded[: min(len(samples), len(padded))] = samples[: len(padded)]
        features = self._model.feature_extractor(padded)[:, : window_s * FRAMES_PER_S]
        encoded = self._model.model.encode(
            ctranslate2.StorageView.from_array(np.ascontiguousarray(features[None]))
        )
        result = self._model.model.generate(
            encoded,
            [self._prompt],
            beam_size=1,
            max_length=min(448, 24 + int(seconds * 10)),
            suppress_blank=True,
            suppress_tokens=self._suppress,
            return_no_speech_prob=True,
            return_scores=True,
        )[0]
        tokens = [t for t in result.sequences_ids[0] if t < self._tokenizer.eot]
        # Score normalisé par la longueur : c'est la log-probabilité moyenne par jeton.
        logprob = float(result.scores[0]) if result.scores else 0.0
        return self._tokenizer.decode(tokens), float(result.no_speech_prob), logprob

    def _standard(self, samples: Any) -> tuple[str, float, float]:
        segments, _ = self._model.transcribe(
            samples,
            language=self._language,
            beam_size=1,
            vad_filter=False,
            condition_on_previous_text=False,
            without_timestamps=True,
        )
        parts = list(segments)
        no_speech = max((s.no_speech_prob for s in parts), default=1.0)
        logprob = min((s.avg_logprob for s in parts), default=-10.0)
        return " ".join(s.text.strip() for s in parts), no_speech, logprob


# --------------------------------------------------------------------------- Cartesia (en flux)

CARTESIA_STT_URL = "wss://api.cartesia.ai/stt/websocket"
CARTESIA_STT_MODEL = "ink-2"
CARTESIA_VERSION = "2026-08-14"
#: Mots que la transcription doit reconnaître en priorité.
KEYTERMS = ("Jarvis",)
_FINALIZE = b""
#: Connexions en cours de fermeture (gardées pour que la tâche ne soit pas oubliée).
_CLOSING: set[asyncio.Future[None]] = set()


class SttError(Exception):
    """La transcription en ligne a échoué : le pipeline repasse sur Whisper local."""


class SttStream(Protocol):
    def send(self, pcm: Pcm) -> None: ...

    def flush(self) -> None: ...

    async def finish(self, timeout_s: float = 3.0) -> Transcript: ...

    async def cancel(self) -> None: ...


class StreamingTranscriber(Protocol):
    name: str

    @property
    def available(self) -> bool: ...

    def open(self) -> SttStream: ...


class CartesiaSTT:
    """Cartesia Ink-2 : l'audio part pendant que l'on parle, le texte est prêt à la fin.

    Mesuré ici (15/10/2026) : texte final 150 ms après la fin de la phrase ; sur un micro
    faible et bruité, 0 % d'erreurs là où Whisper base en faisait 93 %.
    """

    name = "cartesia"

    def __init__(
        self,
        api_key: Callable[[], str | None],
        *,
        connect: Callable[..., Any] | None = None,
        keyterms: tuple[str, ...] = KEYTERMS,
    ) -> None:
        self._api_key = api_key
        self._connect = connect
        self._keyterms = keyterms

    @property
    def available(self) -> bool:
        return bool(self._api_key())

    def url(self) -> str:
        params = {
            "model": CARTESIA_STT_MODEL,
            "encoding": "pcm_s16le",
            "sample_rate": str(RATE),
            "cartesia_version": CARTESIA_VERSION,
        }
        query = "&".join(f"{k}={v}" for k, v in params.items())
        terms = "".join(f"&keyterm={quote(term)}" for term in self._keyterms)
        return f"{CARTESIA_STT_URL}?{query}{terms}"

    def open(self) -> CartesiaSttStream:
        key = self._api_key() or ""
        connect = self._connect
        if connect is None:
            import websockets  # noqa: PLC0415

            connect = websockets.connect
        return CartesiaSttStream(self.url(), {"X-API-Key": key}, connect)


class CartesiaSttStream:
    """Une phrase : l'audio part au fil de l'eau, « finalize » rend le texte de ce qui a été envoyé.

    `flush()` peut être appelé dès une courte pause : si la parole ne reprend pas, le texte
    est déjà là quand la fin de phrase est confirmée.
    """

    def __init__(self, url: str, headers: dict[str, str], connect: Callable[..., Any]) -> None:
        self._url = url
        self._headers = headers
        self._connect = connect
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._finals: list[str] = []
        self._requested = 0
        self._acked = 0
        self._dirty = False
        self._changed = asyncio.Event()
        self._error: BaseException | None = None
        self._samples = 0
        self._ws: Any = None
        self._task = asyncio.create_task(self._run())

    def send(self, pcm: Pcm) -> None:
        if pcm.size:
            self._queue.put_nowait(pcm.astype(np.int16).tobytes())
            self._samples += len(pcm)
            self._dirty = True

    def flush(self) -> None:
        """Demande le texte de tout ce qui a été envoyé (sans fermer le flux)."""
        if self._dirty:
            self._dirty = False
            self._requested += 1
            self._queue.put_nowait(_FINALIZE)

    async def _run(self) -> None:
        try:
            self._ws = await asyncio.wait_for(
                self._connect(self._url, additional_headers=self._headers, max_size=2**20),
                timeout=4.0,
            )
            receiver = asyncio.create_task(self._receive(self._ws))
            try:
                while True:
                    chunk = await self._queue.get()
                    await self._ws.send("finalize" if chunk == _FINALIZE else chunk)
            finally:
                receiver.cancel()
                with contextlib.suppress(BaseException):
                    await receiver
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            self._fail(exc)

    async def _receive(self, ws: Any) -> None:
        try:
            while True:
                message = json.loads(await ws.recv())
                kind = message.get("type")
                if kind == "transcript" and message.get("is_final"):
                    self._finals.append(str(message.get("text", "")))
                elif kind == "flush_done":
                    self._acked += 1
                    self._changed.set()
                elif kind == "error":
                    self._fail(SttError(str(message.get("title") or message.get("message"))))
                    return
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            self._fail(exc)

    def _fail(self, exc: BaseException) -> None:
        self._error = exc
        self._changed.set()

    async def finish(self, timeout_s: float = 3.0) -> Transcript:
        start = time.perf_counter()
        self.flush()
        try:
            async with asyncio.timeout(timeout_s):
                while self._acked < self._requested and self._error is None:
                    self._changed.clear()
                    await self._changed.wait()
        except TimeoutError as exc:
            await self.cancel()
            raise SttError("Cartesia n'a pas rendu le texte à temps") from exc
        if self._error is not None:
            await self.cancel()
            raise SttError(
                f"transcription en ligne : {type(self._error).__name__}"
            ) from self._error
        text = "".join(self._finals).strip()
        # Le texte part tout de suite ; la fermeture polie de la connexion (~1 s) se fait à côté.
        self.close_soon()
        return Transcript(
            text=text,
            audio_s=round(self._samples / RATE, 2),
            duration_ms=round((time.perf_counter() - start) * 1000, 1),
        )

    def close_soon(self) -> None:
        """Ferme la connexion en arrière-plan, sans faire attendre le tour vocal."""
        task = asyncio.ensure_future(self.cancel())
        _CLOSING.add(task)
        task.add_done_callback(_CLOSING.discard)

    async def cancel(self) -> None:
        if not self._task.done():
            self._task.cancel()
            with contextlib.suppress(BaseException):
                await self._task
        ws, self._ws = self._ws, None
        if ws is not None:
            with contextlib.suppress(Exception):
                await ws.close()


# --------------------------------------------------------------------------- Groq (Whisper)

GROQ_STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_STT_MODEL = "whisper-large-v3"
#: Oriente l'orthographe (« Jarvis ») et la langue, sans rien imposer d'autre.
GROQ_PROMPT = "Conversation en français avec Jarvis."


def _retry_after(value: str | None, *, default: float) -> float:
    try:
        return min(max(float(value or default), 1.0), 300.0)
    except ValueError:
        return default


def wav_bytes(audio: Pcm) -> bytes:
    """WAV 16 kHz mono 16 bits en mémoire (rien n'est écrit sur disque)."""
    import io  # noqa: PLC0415
    import wave  # noqa: PLC0415

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(audio.astype(np.int16).tobytes())
    return buffer.getvalue()


class GroqTranscriber:
    """Whisper large-v3 chez Groq, français imposé : la phrase entière, envoyée à la pause.

    Choisi avec Octave le 15/10/2026 : Cartesia Ink-2 devine la langue seul et, avec son
    accent, entendait parfois de l'anglais ; Whisper local (base) comprenait trop mal.
    """

    name = "groq"

    def __init__(
        self,
        api_key: Callable[[], str | None],
        http: Any,
        *,
        model: str = GROQ_STT_MODEL,
        timeout_s: float = 4.0,
    ) -> None:
        self._api_key = api_key
        self._http = http
        self._model = model
        self._timeout_s = timeout_s
        #: Après un « 429 », Groq est laissé de côté le temps qu'il indique.
        self._blocked_until = 0.0

    @property
    def available(self) -> bool:
        return bool(self._api_key()) and time.monotonic() >= self._blocked_until

    async def transcribe(self, audio: Pcm) -> Transcript:
        import httpx  # noqa: PLC0415

        key = self._api_key()
        if not key:
            raise SttError("clé Groq absente")
        start = time.perf_counter()
        try:
            response = await self._http.post(
                GROQ_STT_URL,
                headers={"Authorization": f"Bearer {key}"},
                data={
                    "model": self._model,
                    "language": "fr",
                    "prompt": GROQ_PROMPT,
                    "response_format": "verbose_json",
                    "temperature": "0",
                },
                files={"file": ("phrase.wav", wav_bytes(audio), "audio/wav")},
                timeout=self._timeout_s,
            )
        except httpx.HTTPError as exc:
            raise SttError(f"Groq injoignable : {type(exc).__name__}") from exc
        if response.status_code == 429:
            # Offre gratuite : 20 phrases par minute. On attend ce que Groq demande.
            wait = _retry_after(response.headers.get("retry-after"), default=20.0)
            self._blocked_until = time.monotonic() + wait
            raise SttError(f"Groq limite les requêtes (HTTP 429), pause de {wait:.0f} s")
        if response.status_code != 200:
            raise SttError(f"Groq a refusé la transcription (HTTP {response.status_code})")
        body = response.json()
        segments = [s for s in body.get("segments") or [] if isinstance(s, dict)]
        logprob = min((float(s.get("avg_logprob", 0.0)) for s in segments), default=0.0)
        no_speech = max((float(s.get("no_speech_prob", 0.0)) for s in segments), default=0.0)
        return Transcript(
            text=str(body.get("text", "")).strip(),
            audio_s=round(len(audio) / RATE, 2),
            duration_ms=round((time.perf_counter() - start) * 1000, 1),
            no_speech_prob=round(no_speech, 3),
            avg_logprob=round(logprob, 3),
        )
