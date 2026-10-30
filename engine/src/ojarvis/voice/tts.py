"""Synthèse vocale en flux : Cartesia Sonic (en ligne) et Piper (local, repli hors ligne).

Profil « Tout Meta » : MMS, la voix de Meta, lancée ici sur le processeur, et en secours
espeak-ng, la voix du système (pas un modèle d'IA).

Chaque moteur reçoit les phrases au fil de l'eau et rend l'audio au fil de l'eau :
Jarvis commence à parler pendant que le modèle écrit encore la suite.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import re
import shutil
import subprocess
import time
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import anyio.to_thread
import numpy as np

from ojarvis.core.downloads import PinnedFile
from ojarvis.core.logs import get_logger
from ojarvis.voice.audio import OUTPUT_RATE, resample
from ojarvis.voice.spoken import spoken_french

log = get_logger(__name__)

CARTESIA_URL = "wss://api.cartesia.ai/tts/websocket"
CARTESIA_VERSION = "2026-08-14"
CARTESIA_MODEL = "sonic-3.6"
#: « Étienne » : voix masculine française, posée et précise.
DEFAULT_CARTESIA_VOICE = "c6ccfe32-6bee-484a-a8a2-7a51bee93f99"

PIPER_REVISION = "c10ece1aade47bb51c153c893d14e5bf8e5b7117"
PIPER_BASE = (
    f"https://huggingface.co/rhasspy/piper-voices/resolve/{PIPER_REVISION}/fr/fr_FR/tom/medium"
)
PIPER_VOICE = "fr_FR-tom-medium"
PIPER_FILES: dict[str, PinnedFile] = {
    f"{PIPER_VOICE}.onnx": PinnedFile(
        f"{PIPER_BASE}/{PIPER_VOICE}.onnx",
        "bf65074ccdeeeeaa832e75edb1c0a513c01c9a972bdf085ff8a6e71ea234fd41",
        63_511_038,
    ),
    f"{PIPER_VOICE}.onnx.json": PinnedFile(
        f"{PIPER_BASE}/{PIPER_VOICE}.onnx.json",
        "2f7f885ad5a0aad802e3cc24e4f57239febdcb142b4876de5d238094674361cc",
        4_959,
    ),
}


@dataclass(frozen=True)
class AudioChunk:
    pcm: bytes  # PCM 16 bits mono, petit-boutiste
    rate: int


class TTSError(Exception):
    """Le moteur de synthèse a échoué ; `spoken` dit si du son est déjà sorti."""

    def __init__(self, message: str, *, spoken: bool = False) -> None:
        super().__init__(message)
        self.spoken = spoken


class Synthesizer(Protocol):
    name: str

    @property
    def available(self) -> bool: ...

    async def warm_up(self) -> None: ...

    def stream(self, sentences: AsyncIterator[str]) -> AsyncGenerator[AudioChunk]: ...

    async def close(self) -> None: ...


# --------------------------------------------------------------------------- Cartesia


class CartesiaTTS:
    """WebSocket gardée ouverte entre les tours ; une « context_id » par réponse."""

    name = "cartesia"

    def __init__(
        self,
        api_key: Callable[[], str | None],
        *,
        voice: Callable[[], str] = lambda: DEFAULT_CARTESIA_VOICE,
        connect: Callable[..., Any] | None = None,
        connect_timeout_s: float = 4.0,
    ) -> None:
        self._api_key = api_key
        self._voice = voice
        self._connect = connect
        self._connect_timeout_s = connect_timeout_s
        self._ws: Any = None
        self._lock = asyncio.Lock()

    @property
    def available(self) -> bool:
        return bool(self._api_key())

    async def _connection(self) -> Any:
        async with self._lock:
            if self._ws is not None and getattr(self._ws, "close_code", None) is None:
                return self._ws
            key = self._api_key()
            if not key:
                raise TTSError("clé Cartesia absente")
            connect = self._connect
            if connect is None:
                import websockets  # noqa: PLC0415

                connect = websockets.connect
            self._ws = await asyncio.wait_for(
                connect(
                    f"{CARTESIA_URL}?cartesia_version={CARTESIA_VERSION}",
                    additional_headers={"X-API-Key": key, "Cartesia-Version": CARTESIA_VERSION},
                    max_size=2**22,
                ),
                timeout=self._connect_timeout_s,
            )
            return self._ws

    async def warm_up(self) -> None:
        """Ouvre la connexion à l'avance (au mot de réveil) : 250 ms de gagnées sur le tour."""
        with contextlib.suppress(Exception):
            await self._connection()

    async def close(self) -> None:
        ws, self._ws = self._ws, None
        if ws is not None:
            with contextlib.suppress(Exception):
                await ws.close()

    def _request(self, context_id: str) -> dict[str, Any]:
        return {
            "model_id": CARTESIA_MODEL,
            "voice": {"mode": "id", "id": self._voice()},
            "language": "fr",
            "context_id": context_id,
            "output_format": {
                "container": "raw",
                "encoding": "pcm_s16le",
                "sample_rate": OUTPUT_RATE,
            },
        }

    @staticmethod
    async def _send_all(ws: Any, base: dict[str, Any], sentences: AsyncIterator[str]) -> None:
        first = True
        async for sentence in sentences:
            # Le premier morceau part sans attendre : c'est lui qui fixe la latence.
            delay = 0 if first else 400
            first = False
            message = {**base, "transcript": sentence + " ", "continue": True}
            await ws.send(json.dumps({**message, "max_buffer_delay_ms": delay}))
        await ws.send(json.dumps({**base, "transcript": "", "continue": False}))

    @staticmethod
    async def _receive(
        ws: Any, context_id: str, sender: asyncio.Task[None], spoken: list[bool]
    ) -> AsyncGenerator[AudioChunk]:
        while True:
            if sender.done() and sender.exception() is not None:
                raise TTSError("envoi vers Cartesia interrompu", spoken=bool(spoken))
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=8.0)
            except TimeoutError as exc:
                if not sender.done():
                    continue  # le modèle écrit encore : rien à dire pour l'instant
                raise TTSError("Cartesia ne répond plus", spoken=bool(spoken)) from exc
            message = json.loads(raw)
            if message.get("context_id") not in (None, context_id):
                continue
            kind = message.get("type")
            if kind == "chunk" and message.get("data"):
                spoken.append(True)
                yield AudioChunk(base64.b64decode(message["data"]), OUTPUT_RATE)
            elif kind == "done":
                return
            elif kind == "error":
                detail = message.get("title") or message.get("error_code") or "erreur"
                raise TTSError(f"Cartesia : {detail}", spoken=bool(spoken))

    async def stream(self, sentences: AsyncIterator[str]) -> AsyncGenerator[AudioChunk]:
        try:
            ws = await self._connection()
        except TTSError:
            raise
        except Exception as exc:
            raise TTSError(f"connexion Cartesia impossible : {type(exc).__name__}") from exc
        context_id = uuid.uuid4().hex
        spoken: list[bool] = []
        sender = asyncio.create_task(self._send_all(ws, self._request(context_id), sentences))
        finished = False
        try:
            async with contextlib.aclosing(self._receive(ws, context_id, sender, spoken)) as audio:
                async for chunk in audio:
                    yield chunk
            finished = True
        except TTSError:
            await self.close()
            raise
        except Exception as exc:
            await self.close()
            raise TTSError(f"Cartesia : {type(exc).__name__}", spoken=bool(spoken)) from exc
        finally:
            if not sender.done():
                sender.cancel()
            with contextlib.suppress(BaseException):
                await sender
            if not finished and self._ws is not None:
                with contextlib.suppress(Exception):
                    await self._ws.send(json.dumps({"context_id": context_id, "cancel": True}))


# --------------------------------------------------------------------------- Piper


class PiperTTS:
    """Voix locale (fr_FR « tom »), phrase par phrase, dans un fil séparé."""

    name = "piper"

    def __init__(self, folder: Path, *, voice: str = PIPER_VOICE) -> None:
        self._model_path = folder / f"{voice}.onnx"
        self._voice: Any = None
        self._lock = asyncio.Lock()

    @property
    def available(self) -> bool:
        return self._model_path.is_file()

    def _load(self) -> Any:
        if self._voice is None:
            from piper import PiperVoice  # noqa: PLC0415

            self._voice = PiperVoice.load(self._model_path)
        return self._voice

    async def warm_up(self) -> None:
        async with self._lock:
            await anyio.to_thread.run_sync(self._load)

    async def close(self) -> None:
        return None

    def _synthesize(self, text: str) -> tuple[bytes, int]:
        voice = self._load()
        chunks = list(voice.synthesize(text))
        if not chunks:
            return b"", OUTPUT_RATE
        audio = np.concatenate([c.audio_int16_array for c in chunks])
        rate = int(chunks[0].sample_rate)
        return resample(audio, rate, OUTPUT_RATE).tobytes(), OUTPUT_RATE

    async def stream(self, sentences: AsyncIterator[str]) -> AsyncGenerator[AudioChunk]:
        async for sentence in sentences:
            async with self._lock:
                pcm, rate = await anyio.to_thread.run_sync(self._synthesize, sentence)
            if pcm:
                yield AudioChunk(pcm, rate)


# --------------------------------------------------------------------------- MMS (Meta)

#: MMS TTS français de Meta (facebook/mms-tts-fra), exporté en ONNX : 114 Mo.
MMS_REVISION = "c7aa283bf5b599d3c804e4accab07f6394a2b4ae"
MMS_BASE = f"https://huggingface.co/Xenova/mms-tts-fra/resolve/{MMS_REVISION}"
MMS_FILES: dict[str, PinnedFile] = {
    "model.onnx": PinnedFile(
        f"{MMS_BASE}/onnx/model.onnx",
        "429b27e1cc954d7da4b88e6c73933ad8c3dc033f941e9a04fd2091c1e7ceba41",
        114_263_414,
    ),
    "vocab.json": PinnedFile(
        f"{MMS_BASE}/vocab.json",
        "d11c7389cb4eec1237a964f18ed1973a47c8b6db6ad0726c065dd2ade6a9c5eb",
        493,
    ),
}
MMS_RATE = 16_000
#: MMS ne lit pas la ponctuation : un court silence sépare les morceaux d'une phrase.
MMS_PAUSE_S = 0.18
_PIECES = re.compile(r"\s*[,;:()\u2013\u2014]\s*")


class MmsTTS:
    """La voix de Meta (MMS, français), phrase par phrase, dans un fil séparé.

    Essai du 30/10/2026 sur un i5-4200M : 4,4 s de calcul pour 8,9 s de voix, la version
    complète allant plus vite que la version quantifiée.
    """

    name = "mms"

    def __init__(self, folder: Path) -> None:
        self._folder = folder
        self._session: Any = None
        self._vocab: dict[str, int] = {}
        self._lock = asyncio.Lock()

    @property
    def available(self) -> bool:
        return all((self._folder / name).is_file() for name in MMS_FILES)

    def _load(self) -> Any:
        if self._session is None:
            import onnxruntime as ort  # noqa: PLC0415

            options = ort.SessionOptions()
            options.log_severity_level = 4
            self._vocab = json.loads((self._folder / "vocab.json").read_text(encoding="utf-8"))
            self._session = ort.InferenceSession(
                str(self._folder / "model.onnx"),
                sess_options=options,
                providers=["CPUExecutionProvider"],
            )
        return self._session

    def _ids(self, text: str) -> list[int]:
        # Comme le découpage de MMS : un jeton vide (0) entre chaque lettre connue.
        ids = [0]
        for char in text.lower():
            if char in self._vocab:
                ids += [self._vocab[char], 0]
        return ids

    def _synthesize(self, sentence: str) -> bytes:
        session = self._load()
        pause = np.zeros(int(MMS_PAUSE_S * MMS_RATE), dtype=np.float32)
        audio: list[np.ndarray[Any, Any]] = []
        for piece in _PIECES.split(spoken_french(sentence)):
            ids = self._ids(piece)
            if len(ids) < 3:  # rien de prononçable
                continue
            feeds = {
                "input_ids": np.array([ids], dtype=np.int64),
                "attention_mask": np.ones((1, len(ids)), dtype=np.int64),
            }
            wave = np.asarray(session.run(None, feeds)[0], dtype=np.float32).reshape(-1)
            audio += [pause, wave] if audio else [wave]
        if not audio:
            return b""
        pcm = (np.clip(np.concatenate(audio), -1.0, 1.0) * 32767).astype(np.int16)
        return resample(pcm, MMS_RATE, OUTPUT_RATE).tobytes()

    def _warm(self) -> None:
        if self._session is None:
            self._load()
            # La première phrase coûte 2 s de plus (essai du 30/10) : on la paie au démarrage.
            self._synthesize("Bonjour.")

    async def warm_up(self) -> None:
        async with self._lock:
            await anyio.to_thread.run_sync(self._warm)

    async def close(self) -> None:
        return None

    async def stream(self, sentences: AsyncIterator[str]) -> AsyncGenerator[AudioChunk]:
        spoken = False
        async for sentence in sentences:
            try:
                async with self._lock:
                    pcm = await anyio.to_thread.run_sync(self._synthesize, sentence)
            except Exception as exc:
                raise TTSError(f"MMS : {type(exc).__name__}", spoken=spoken) from exc
            if pcm:
                spoken = True
                yield AudioChunk(pcm, OUTPUT_RATE)


# --------------------------------------------------------------------------- espeak-ng


class EspeakTTS:
    """La voix du système (espeak-ng, installé avec Ubuntu) : pas un modèle d'IA."""

    name = "espeak"

    def __init__(self, *, voice: str = "fr", words_per_minute: int = 165) -> None:
        self._voice = voice
        self._speed = words_per_minute

    @property
    def available(self) -> bool:
        return shutil.which("espeak-ng") is not None

    async def warm_up(self) -> None:
        return None

    async def close(self) -> None:
        return None

    def _synthesize(self, sentence: str) -> bytes:
        binary = shutil.which("espeak-ng")
        if binary is None:
            raise TTSError("espeak-ng absent")
        # Le texte passe par l'entrée standard : une phrase qui commence par « - » n'est pas
        # prise pour une option.
        done = subprocess.run(  # noqa: S603 — binaire système, arguments fixes
            [binary, "-v", self._voice, "-s", str(self._speed), "--stdout"],
            input=sentence.encode(),
            capture_output=True,
            timeout=30,
            check=False,
        )
        wav = done.stdout
        if done.returncode != 0 or len(wav) <= 44:
            raise TTSError(f"espeak-ng a échoué (code {done.returncode})")
        rate = int.from_bytes(wav[24:28], "little")  # en-tête WAV, tailles laissées vides
        pcm = np.frombuffer(wav[44 : 44 + (len(wav) - 44) // 2 * 2], dtype=np.int16)
        return resample(pcm, rate, OUTPUT_RATE).tobytes()

    async def stream(self, sentences: AsyncIterator[str]) -> AsyncGenerator[AudioChunk]:
        async for sentence in sentences:
            pcm = await anyio.to_thread.run_sync(self._synthesize, sentence)
            if pcm:
                yield AudioChunk(pcm, OUTPUT_RATE)


# --------------------------------------------------------------------------- repli


@dataclass
class _Replay:
    """Garde les phrases déjà lues pour pouvoir les redonner au moteur de secours."""

    source: AsyncIterator[str]
    seen: list[str] = field(default_factory=list)
    exhausted: bool = False

    async def live(self) -> AsyncIterator[str]:
        async for sentence in self.source:
            self.seen.append(sentence)
            yield sentence
        self.exhausted = True

    async def from_index(self, index: int) -> AsyncIterator[str]:
        for sentence in self.seen[index:]:
            yield sentence
        if not self.exhausted:
            async for sentence in self.live():
                yield sentence


class FallbackTTS:
    """Cartesia (ou MMS) d'abord ; Piper (ou espeak-ng) prend le relais si le premier échoue,
    même en cours de réponse.

    Après un échec, le premier est mis de côté pendant `cooldown_s` : les réponses suivantes
    partent directement sur le secours, sans attendre un nouvel échec.
    """

    name = "auto"

    def __init__(
        self,
        primary: Synthesizer,
        secondary: Synthesizer,
        *,
        cooldown_s: float = 60.0,
        on_fallback: Callable[[str], None] | None = None,
        prefer_secondary: Callable[[], bool] = lambda: False,
    ) -> None:
        self.primary = primary
        self.secondary = secondary
        self._cooldown_s = cooldown_s
        self._degraded_until = 0.0
        self._on_fallback = on_fallback
        self._prefer_secondary = prefer_secondary
        self.last_engine: str | None = None

    @property
    def available(self) -> bool:
        return self.primary.available or self.secondary.available

    def _use_primary(self) -> bool:
        return (
            not self._prefer_secondary()
            and self.primary.available
            and time.monotonic() >= self._degraded_until
        )

    async def warm_up(self) -> None:
        if self._use_primary():
            await self.primary.warm_up()
        else:
            await self.secondary.warm_up()

    async def close(self) -> None:
        await self.primary.close()
        await self.secondary.close()

    async def stream(self, sentences: AsyncIterator[str]) -> AsyncGenerator[AudioChunk]:
        replay = _Replay(sentences)
        start_index = 0
        if self._use_primary():
            self.last_engine = self.primary.name
            sent = 0
            try:
                async with contextlib.aclosing(self.primary.stream(replay.live())) as chunks:
                    async for chunk in chunks:
                        yield chunk
                return
            except TTSError as error:
                self._degraded_until = time.monotonic() + self._cooldown_s
                log.warning("tts_fallback", engine=self.primary.name, error=str(error))
                if self._on_fallback is not None:
                    self._on_fallback(str(error))
                # Déjà parlé : on reprend à la phrase en cours ; sinon tout depuis le début.
                sent = max(len(replay.seen) - 1, 0) if error.spoken else 0
            start_index = sent
        self.last_engine = self.secondary.name
        async with contextlib.aclosing(
            self.secondary.stream(replay.from_index(start_index))
        ) as chunks:
            async for chunk in chunks:
                yield chunk
