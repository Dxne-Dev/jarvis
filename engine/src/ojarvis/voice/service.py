"""Service vocal : démarre, arrête et reconfigure le pipeline selon les réglages.

Il est découplé du chat : sans micro, sans modèle ou sur une erreur, le reste du moteur
continue ; l'état et la raison sont visibles dans l'interface. Les modèles locaux
(mot de réveil, transcription, voix de secours) sont téléchargés une fois et vérifiés.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import shutil
import subprocess
import time
from collections.abc import Callable, Coroutine
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import anyio.to_thread
import httpx

from ojarvis.chat.service import ChatService
from ojarvis.core.downloads import PinnedFile, fetch_pinned, files_present
from ojarvis.core.logs import get_logger
from ojarvis.events.bus import EventBus
from ojarvis.security.secrets import SecretStore
from ojarvis.settings_store import Preferences
from ojarvis.tracing.tracer import Tracer
from ojarvis.voice.audio import (
    AudioSink,
    AudioSource,
    MicrophoneSilentError,
    MicrophoneSource,
    SpeakerSink,
)
from ojarvis.voice.pipeline import TurnReport, VoiceConfig, VoicePipeline, VoiceState
from ojarvis.voice.stt import (
    WHISPER_FILES,
    CartesiaSTT,
    CloudTranscriber,
    GroqTranscriber,
    StreamingTranscriber,
    WhisperTranscriber,
)
from ojarvis.voice.tts import (
    CARTESIA_VERSION,
    PIPER_FILES,
    CartesiaTTS,
    FallbackTTS,
    PiperTTS,
)
from ojarvis.voice.vad import EndpointConfig, SileroVad
from ojarvis.voice.wake import WAKE_FILES, OpenWakeWord

log = get_logger(__name__)

MODEL_SETS: dict[str, tuple[str, dict[str, PinnedFile]]] = {
    "reveil": ("openwakeword", WAKE_FILES),
    "transcription": ("faster-whisper-base", WHISPER_FILES),
    "voix_locale": ("piper", PIPER_FILES),
}

#: Seuils du mot de réveil selon la sensibilité choisie dans Réglages.
SENSITIVITY: dict[str, tuple[float, float, bool]] = {
    "basse": (0.6, 0.3, False),
    "normale": (0.5, 0.15, True),
    "haute": (0.35, 0.1, True),
}

EC_SOURCE = "ojarvis_micro"
EC_SINK = "ojarvis_sortie"
RETRY_DELAYS_S: tuple[float, ...] = (5.0, 15.0, 60.0)


@dataclass
class VoiceStatus:
    state: str = VoiceState.OFF.value
    enabled: bool = False
    error: str | None = None
    models: dict[str, str] = field(default_factory=dict)
    echo_cancel: bool = False
    tts_engine: str | None = None
    tts_fallback: str | None = None
    stt_engine: str | None = None
    #: La transcription en ligne était voulue mais Whisper local a pris le relais.
    stt_fallback: bool = False
    last_latency_ms: float | None = None
    last_turn_at: float | None = None


class EchoCancel:
    """Annulation d'écho de PipeWire : Jarvis ne s'entend pas parler et peut être coupé à la voix.

    Le module crée un micro et une sortie virtuels ; les périphériques par défaut du
    système ne changent pas. Il est déchargé à l'arrêt du moteur.
    """

    def __init__(self) -> None:
        self.module_id: str | None = None

    @staticmethod
    def _pactl(*args: str) -> str:
        pactl = shutil.which("pactl")
        if pactl is None:
            raise RuntimeError("pactl absent")
        done = subprocess.run(  # noqa: S603 — binaire système, arguments fixes
            [pactl, *args], check=True, capture_output=True, text=True, timeout=5
        )
        return done.stdout

    def _existing(self) -> str | None:
        for line in self._pactl("list", "short", "modules").splitlines():
            parts = line.split("\t")
            if len(parts) >= 3 and "module-echo-cancel" in parts[1] and EC_SOURCE in parts[2]:
                return parts[0]
        return None

    def load(self, source: str | None, sink: str | None) -> bool:
        try:
            existing = self._existing()
            if existing is not None:
                self.module_id = existing
                return True
            args = [
                "load-module",
                "module-echo-cancel",
                "aec_method=webrtc",
                f"source_name={EC_SOURCE}",
                f"sink_name={EC_SINK}",
                'source_properties=device.description="O-jarvis micro"',
                'sink_properties=device.description="O-jarvis sortie"',
            ]
            if source:
                args.append(f"source_master={source}")
            if sink:
                args.append(f"sink_master={sink}")
            self.module_id = self._pactl(*args).strip() or None
        except Exception as exc:
            log.warning("echo_cancel_unavailable", error=type(exc).__name__)
            return False
        return self.module_id is not None

    def unload(self) -> None:
        module, self.module_id = self.module_id, None
        if module is None:
            return
        with contextlib.suppress(Exception):
            self._pactl("unload-module", module)


def _refresh_devices() -> None:
    """PortAudio ne voit les nouveaux périphériques qu'après une réinitialisation.

    À n'appeler que micro et sortie fermés : réinitialiser PortAudio pendant l'écoute
    coupe le micro sans prévenir.
    """
    try:
        import sounddevice as sd  # noqa: PLC0415
    except (ImportError, OSError):  # pas de PortAudio sur la machine : rien à rafraîchir
        return
    with contextlib.suppress(Exception):
        sd._terminate()
        sd._initialize()


def _pactl_devices(kind: str) -> list[dict[str, str]]:
    """Micros (`sources`) ou sorties (`sinks`) vus par PipeWire, avec un nom lisible."""
    pactl = shutil.which("pactl")
    if pactl is None:
        raise RuntimeError("pactl absent")
    done = subprocess.run(  # noqa: S603 — binaire système, arguments fixes
        [pactl, "--format=json", "list", kind],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    devices = []
    for item in json.loads(done.stdout):
        name = str(item.get("name", ""))
        props = item.get("properties", {})
        if not name or name.startswith("ojarvis_") or props.get("device.class") == "monitor":
            continue
        label = item.get("description")
        if not label or label == "(null)":
            label = props.get("device.description") or props.get("node.nick") or name
        devices.append({"name": name, "label": str(label)})
    return devices


def list_devices() -> dict[str, list[dict[str, str]]]:
    """Ne touche jamais à PortAudio : le réinitialiser couperait le micro en cours d'écoute."""
    return {"inputs": _pactl_devices("sources"), "outputs": _pactl_devices("sinks")}


class VoiceService:
    def __init__(
        self,
        *,
        models_dir: Path,
        http: httpx.AsyncClient,
        bus: EventBus,
        tracer: Tracer,
        chat: ChatService,
        secrets: SecretStore,
        preferences: Callable[[], Preferences],
        audio: bool = True,
        parts: dict[str, Any] | None = None,
        source_factory: Callable[[str | None], AudioSource] = MicrophoneSource,
        sink_factory: Callable[[str | None], AudioSink] = SpeakerSink,
        echo: EchoCancel | None = None,
        clock: Callable[[], float] = time.monotonic,
        on_listen: Callable[[], None] | None = None,
    ) -> None:
        self._on_listen = on_listen
        self._source_factory = source_factory
        self._sink_factory = sink_factory
        self._clock = clock
        self._models = models_dir
        self._http = http
        self._bus = bus
        self._tracer = tracer
        self._chat = chat
        self._secrets = secrets
        self._preferences = preferences
        self._audio = audio
        self.status = VoiceStatus()
        self._pipeline: VoicePipeline | None = None
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._echo = echo or EchoCancel()
        #: Composants chargés une fois (modèles) ; fournis directement par les tests.
        self._parts: dict[str, Any] = dict(parts or {})
        self._preloaded = parts is not None
        self._applied: dict[str, Any] = {}
        self._voices_cache: tuple[float, list[dict[str, Any]]] | None = None
        self._background: set[asyncio.Future[Any]] = set()
        self.retry_delays_s = RETRY_DELAYS_S

    # ------------------------------------------------------------------ état

    def _spawn(self, coroutine: Coroutine[Any, Any, Any]) -> None:
        task = asyncio.ensure_future(coroutine)
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    def snapshot(self) -> dict[str, Any]:
        data = asdict(self.status)
        data["frames"] = self._pipeline.frames_seen if self._pipeline is not None else 0
        if self._pipeline is not None and self.status.error is None:
            data["state"] = self._pipeline.state.value
        return data

    async def _publish(self) -> None:
        await self._bus.publish("voice.status", self.snapshot(), persist=False)

    def _model_status(self) -> dict[str, str]:
        return {
            key: "prêt" if files_present(self._models / folder, files) else "absent"
            for key, (folder, files) in MODEL_SETS.items()
        }

    # ------------------------------------------------------------------ démarrage

    async def start(self) -> None:
        async with self._lock:
            await self._start_locked()

    async def _start_locked(self) -> None:
        prefs = self._preferences()
        self.status.enabled = prefs.voice_enabled
        self.status.models = (
            dict.fromkeys(MODEL_SETS, "simulé") if self._preloaded else self._model_status()
        )
        if not prefs.voice_enabled or not self._audio:
            self.status.state = VoiceState.OFF.value
            self.status.error = None if self._audio else "Audio désactivé pour ce lancement."
            await self._publish()
            return
        self.status.state = "starting"
        self.status.error = None
        await self._publish()
        try:
            if not self._preloaded:
                await self._ensure_models()
                await self._load_parts()
            await self._launch(prefs)
        except Exception as exc:
            log.exception("voice_start_failed")
            self.status.state = VoiceState.ERROR.value
            self.status.error = _describe(exc)
            await self._publish()

    async def _ensure_models(self) -> None:
        for key, (folder, files) in MODEL_SETS.items():
            target = self._models / folder
            if files_present(target, files):
                continue
            last = [0.0]

            def progress(
                _name: str, done: int, total: int | None, key: str = key, last: list[float] = last
            ) -> None:
                if total and time.monotonic() - last[0] > 1.0:
                    last[0] = time.monotonic()
                    self.status.models[key] = f"téléchargement {done * 100 // total} %"
                    self._spawn(self._publish())

            self.status.models[key] = "téléchargement"
            await self._publish()
            await fetch_pinned(self._http, target, files, on_progress=progress)
            self.status.models[key] = "prêt"
        await self._publish()

    async def _load_parts(self) -> None:
        if self._parts:
            return
        wake = await anyio.to_thread.run_sync(OpenWakeWord, self._models / "openwakeword")
        vad = await anyio.to_thread.run_sync(SileroVad)
        stt = WhisperTranscriber(self._models / "faster-whisper-base")
        await anyio.to_thread.run_sync(stt.load)
        piper = PiperTTS(self._models / "piper")
        await piper.warm_up()
        cartesia = CartesiaTTS(
            lambda: self._secrets.get("CARTESIA_API_KEY"),
            voice=lambda: self._preferences().voice_name,
        )
        tts = FallbackTTS(
            cartesia,
            piper,
            on_fallback=self._on_tts_fallback,
            prefer_secondary=lambda: self._preferences().voice_engine == "piper",
        )
        self._parts = {
            "wake": wake,
            "vad": vad,
            "stt": stt,
            "tts": tts,
            "cloud_stt": GroqTranscriber(lambda: self._secrets.get("GROQ_API_KEY"), self._http),
            "streaming_stt": CartesiaSTT(lambda: self._secrets.get("CARTESIA_API_KEY")),
        }

    def _on_tts_fallback(self, reason: str) -> None:
        self.status.tts_fallback = reason
        self._spawn(self._bus.publish("voice.tts_fallback", {"reason": reason, "engine": "piper"}))

    def _config(self, prefs: Preferences, *, echo_cancel: bool) -> VoiceConfig:
        threshold, candidate, verify = SENSITIVITY[prefs.wake_sensitivity]
        return VoiceConfig(
            wake_threshold=threshold,
            wake_candidate=candidate,
            verify_wake=verify,
            follow_up_s=6.0 if prefs.voice_follow_up else 0.0,
            # Sans annulation d'écho, Jarvis s'entendrait parler : seule la phrase
            # « Hey Jarvis » peut alors le couper (sauf casque, réglage explicite).
            barge_in=prefs.voice_barge_in and (echo_cancel or prefs.voice_headset),
            endpoint=EndpointConfig(),
        )

    async def _launch(self, prefs: Preferences) -> None:
        echo = await anyio.to_thread.run_sync(
            self._echo.load, prefs.voice_input_device, prefs.voice_output_device
        )
        if echo and self._source_factory is MicrophoneSource:
            await anyio.to_thread.run_sync(_refresh_devices)
        self.status.echo_cancel = echo
        sink = self._sink_factory(EC_SINK if echo else prefs.voice_output_device)

        def make_pipeline() -> VoicePipeline:
            current = self._preferences()
            return VoicePipeline(
                source=self._source_factory(EC_SOURCE if echo else current.voice_input_device),
                sink=sink,
                wake=self._parts["wake"],
                vad=self._parts["vad"],
                stt=self._parts["stt"],
                tts=self._parts["tts"],
                chat=self._chat,
                bus=self._bus,
                tracer=self._tracer,
                config=self._config(current, echo_cancel=echo),
                on_turn=self._on_turn,
                clock=self._clock,
                streaming_stt=self._streaming_for(current),
                cloud_stt=self._cloud_for(current),
            )

        self._pipeline = make_pipeline()
        self._applied = _device_prefs(prefs)
        self._task = asyncio.create_task(self._run(make_pipeline, sink))
        self.status.state = VoiceState.IDLE.value
        await self._publish()

    async def _run(self, make_pipeline: Callable[[], VoicePipeline], sink: AudioSink) -> None:
        """Fait tourner le pipeline ; s'il tombe (micro débranché…), réessaie un peu plus tard."""
        attempt = 0
        try:
            while True:
                pipeline = self._pipeline or make_pipeline()
                self._pipeline = pipeline
                started = time.monotonic()
                try:
                    await pipeline.run()
                    return
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    log.exception("voice_pipeline_failed")
                    self.status.state = VoiceState.ERROR.value
                    self.status.error = _describe(exc)
                    await self._publish()
                if time.monotonic() - started > 120:
                    attempt = 0
                delays = self.retry_delays_s
                if attempt >= len(delays):
                    return
                await asyncio.sleep(delays[attempt])
                attempt += 1
                self._pipeline = make_pipeline()
                self.status.error = None
                self.status.state = VoiceState.IDLE.value
                await self._publish()
        finally:
            await sink.close()

    def _streaming_for(self, prefs: Preferences) -> StreamingTranscriber | None:
        """Cartesia en flux : choisi, ou en relais de Groq si sa clé manque."""
        if prefs.voice_stt == "local":
            return None
        engine: StreamingTranscriber | None = self._parts.get("streaming_stt")
        return engine

    def _cloud_for(self, prefs: Preferences) -> CloudTranscriber | None:
        """Groq (Whisper large-v3) par phrase ; Whisper local reste le dernier secours."""
        if prefs.voice_stt != "groq":
            return None
        engine: CloudTranscriber | None = self._parts.get("cloud_stt")
        return engine

    def _on_turn(self, report: TurnReport) -> None:
        self.status.last_latency_ms = report.latency_ms
        self.status.last_turn_at = time.time()
        self.status.tts_engine = report.tts_engine
        self.status.stt_engine = report.stt_engine
        pipeline = self._pipeline
        wanted = pipeline is not None and (
            pipeline.streaming_stt is not None or pipeline.cloud_stt is not None
        )
        self.status.stt_fallback = wanted and report.stt_engine != "cartesia"
        if report.tts_engine == "cartesia":
            self.status.tts_fallback = None

    # ------------------------------------------------------------------ arrêt et réglages

    async def stop(self) -> None:
        async with self._lock:
            await self._stop_locked()
            self.status.state = VoiceState.OFF.value
            await self._publish()

    async def _stop_locked(self) -> None:
        task, self._task = self._task, None
        self._pipeline = None
        if task is not None:
            task.cancel()
            with contextlib.suppress(BaseException):
                await task
        await anyio.to_thread.run_sync(self._echo.unload)

    async def close(self) -> None:
        await self.stop()
        tts = self._parts.get("tts")
        if tts is not None:
            await tts.close()

    async def apply(self, prefs: Preferences) -> None:
        """Nouveaux réglages : redémarre seulement si c'est nécessaire."""
        async with self._lock:
            running = self._task is not None and not self._task.done()
            if not prefs.voice_enabled:
                if running:
                    await self._stop_locked()
                self.status.enabled = False
                self.status.state = VoiceState.OFF.value
                await self._publish()
                return
            if running and _device_prefs(prefs) == self._applied and self._pipeline is not None:
                self._pipeline.config = self._config(prefs, echo_cancel=self.status.echo_cancel)
                self._pipeline.streaming_stt = self._streaming_for(prefs)
                self._pipeline.cloud_stt = self._cloud_for(prefs)
                await self._publish()
                return
            if running:
                await self._stop_locked()
            await self._start_locked()

    # ------------------------------------------------------------------ commandes

    def listen_now(self) -> bool:
        if self._pipeline is None:
            return False
        self._pipeline.listen_now()
        if self._on_listen is not None:
            self._on_listen()
        return True

    async def interrupt(self) -> bool:
        if self._pipeline is None:
            return False
        await self._pipeline.interrupt(by="interface")
        return True

    async def voices(self) -> list[dict[str, Any]]:
        """Voix françaises de Cartesia (mises en cache dix minutes)."""
        if self._voices_cache and time.monotonic() - self._voices_cache[0] < 600:
            return self._voices_cache[1]
        key = self._secrets.get("CARTESIA_API_KEY")
        if not key:
            return []
        response = await self._http.get(
            "https://api.cartesia.ai/voices",
            params={"language": "fr", "limit": 100},
            headers={"X-API-Key": key, "Cartesia-Version": CARTESIA_VERSION},
        )
        response.raise_for_status()
        body = response.json()
        items = body.get("data", body) if isinstance(body, dict) else body
        voices = [
            {
                "id": str(v["id"]),
                "name": str(v.get("name", "")),
                "gender": v.get("gender"),
                "description": str(v.get("description") or "")[:160],
            }
            for v in items
            if isinstance(v, dict) and v.get("language") in (None, "fr")
        ]
        self._voices_cache = (time.monotonic(), voices)
        return voices


def _device_prefs(prefs: Preferences) -> dict[str, Any]:
    return {"input": prefs.voice_input_device, "output": prefs.voice_output_device}


def _describe(exc: Exception) -> str:
    if isinstance(exc, MicrophoneSilentError):
        return "Le micro ne transmet plus rien. Nouvel essai en cours…"
    text = str(exc)
    if "PortAudio" in text or "Invalid device" in text or "No Default" in text:
        return "Micro ou haut-parleur introuvable."
    if isinstance(exc, httpx.HTTPError):
        return "Téléchargement d'un modèle vocal impossible (réseau)."
    return "Le pipeline vocal n'a pas pu démarrer."
