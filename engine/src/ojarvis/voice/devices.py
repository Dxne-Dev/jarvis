"""Micro, haut-parleur et annulation d'écho (PipeWire), vus sans réveiller PortAudio, et les
erreurs audio dites en clair.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import subprocess
from pathlib import Path

import httpx

from ojarvis.core.downloads import ChecksumError
from ojarvis.core.logs import get_logger
from ojarvis.security.redaction import REDACTOR
from ojarvis.voice.audio import (
    MicrophoneSilentError,
)

log = get_logger(__name__)

EC_SOURCE = "ojarvis_micro"

EC_SINK = "ojarvis_sortie"


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


def _portaudio_sees(name: str, kind: str) -> bool:
    """Vrai si PortAudio trouve ce micro (`input`) ou cette sortie (`output`) par son nom."""
    try:
        import sounddevice as sd  # noqa: PLC0415

        sd.query_devices(name, kind)
    except Exception:
        return False
    return True


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


#: Erreurs audio reconnues à leur texte, la plus précise d'abord.
_AUDIO_ERRORS: tuple[tuple[str, str], ...] = (
    (
        "PortAudio library not found",
        "La bibliothèque audio manque : installe-la avec « sudo apt install libportaudio2 ».",
    ),
    ("PortAudio", "Micro ou haut-parleur introuvable."),
    ("Invalid device", "Micro ou haut-parleur introuvable."),
    ("No Default", "Micro ou haut-parleur introuvable."),
)


def _describe(exc: Exception) -> str:
    if isinstance(exc, MicrophoneSilentError):
        return "Le micro ne transmet plus rien. Nouvel essai en cours…"
    text = str(exc)
    for needle, message in _AUDIO_ERRORS:
        if needle in text:
            return message
    if isinstance(exc, httpx.HTTPError):
        return (
            "Téléchargement d'un modèle vocal impossible (réseau). "
            "Réessaie ou télécharge-le à la main : Réglages › Modèles locaux."
        )
    if isinstance(exc, ChecksumError):
        return "Un modèle vocal reçu était abîmé : il a été supprimé. Réessaie."
    if isinstance(exc, ImportError):
        missing = exc.name or _cause(exc)
        return f"Une bibliothèque de la voix manque ({missing}) : réinstalle O-jarvis."
    return f"Le pipeline vocal n'a pas pu démarrer ({_cause(exc)})."


def _cause(exc: Exception) -> str:
    """Première ligne de l'erreur, sans dossier personnel ni secret, assez courte pour l'écran."""
    lines = str(exc).strip().splitlines()
    text = lines[0] if lines else ""
    text = REDACTOR.redact(text.replace(str(Path.home()), "~"))
    if len(text) > 160:
        text = text[:159] + "…"
    return f"{type(exc).__name__} : {text}" if text else type(exc).__name__
