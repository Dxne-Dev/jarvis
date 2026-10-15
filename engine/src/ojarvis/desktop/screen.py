"""Capture de l'écran : portail xdg-desktop-portal sous Wayland, X11 en direct.

- Wayland (GNOME 50 ici) : seule voie possible, le portail `org.freedesktop.portal.Screenshot`
  (D-Bus). Il enregistre une image et en rend l'adresse ; Jarvis la lit, puis l'efface.
- X11 : capture directe (`mss`). Sert aussi aux tests, sous Xvfb.

L'image est réduite (le texte reste lisible, le modèle de vision va plus vite) et réencodée
en JPEG ; elle ne quitte la machine que si tu as choisi la lecture d'écran « en ligne ».
"""

from __future__ import annotations

import asyncio
import io
import os
import secrets
from pathlib import Path
from urllib.parse import unquote, urlsplit

from ojarvis.core.errors import UnavailableError
from ojarvis.core.logs import get_logger

log = get_logger(__name__)

PORTAL_TIMEOUT_S = 30.0


def session_type() -> str:
    """« wayland » ou « x11 » (la variable du système, sinon la présence d'un affichage)."""
    kind = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if kind in ("wayland", "x11"):
        return kind
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    return "x11" if os.environ.get("DISPLAY") else "aucun"


def shrink(png_or_any: bytes, *, max_side: int) -> bytes:
    """Image réduite (plus grand côté ≤ max_side) en JPEG : moins de jetons pour le modèle."""
    from PIL import Image  # noqa: PLC0415

    with Image.open(io.BytesIO(png_or_any)) as image:
        rgb = image.convert("RGB")
        rgb.thumbnail((max_side, max_side))
        out = io.BytesIO()
        rgb.save(out, "JPEG", quality=85)
        return out.getvalue()


def _capture_x11() -> bytes:
    import mss  # noqa: PLC0415
    import mss.tools  # noqa: PLC0415

    with mss.MSS() as grabber:
        monitor = grabber.monitors[0]  # tous les écrans réunis
        shot = grabber.grab(monitor)
        png = mss.tools.to_png(shot.rgb, shot.size)
    if png is None:  # pragma: no cover - to_png rend des octets sans fichier de sortie
        raise UnavailableError("Capture X11 impossible.")
    return png


def _capture_portal() -> bytes:
    """Demande une capture au portail (sans boîte de dialogue), attend sa réponse."""
    from jeepney import DBusAddress, MatchRule, new_method_call  # noqa: PLC0415
    from jeepney.bus_messages import message_bus  # noqa: PLC0415
    from jeepney.io.blocking import open_dbus_connection  # noqa: PLC0415

    token = "ojarvis" + secrets.token_hex(6)
    with open_dbus_connection(bus="SESSION") as connection:
        sender = (connection.unique_name or "").lstrip(":").replace(".", "_")
        rule = MatchRule(
            type="signal",
            interface="org.freedesktop.portal.Request",
            member="Response",
            path=f"/org/freedesktop/portal/desktop/request/{sender}/{token}",
        )
        # La réponse arrive par un signal : on s'y abonne avant de poser la question.
        connection.send_and_get_reply(message_bus.AddMatch(rule))
        with connection.filter(rule) as responses:
            portal = DBusAddress(
                "/org/freedesktop/portal/desktop",
                bus_name="org.freedesktop.portal.Desktop",
                interface="org.freedesktop.portal.Screenshot",
            )
            options = {"handle_token": ("s", token), "interactive": ("b", False)}
            connection.send_and_get_reply(
                new_method_call(portal, "Screenshot", "sa{sv}", ("", options)), timeout=10
            )
            signal = connection.recv_until_filtered(responses, timeout=PORTAL_TIMEOUT_S)
    code, results = signal.body
    if code != 0:
        raise UnavailableError("Capture refusée par le portail (accès à l'écran non autorisé).")
    uri = results.get("uri", ("s", ""))[1]
    path = Path(unquote(urlsplit(uri).path))
    try:
        return path.read_bytes()
    finally:
        # Le portail a écrit la capture sur le disque : on ne la garde pas.
        path.unlink(missing_ok=True)


async def capture() -> bytes:
    """Capture brute de l'écran (PNG), selon la session."""
    kind = session_type()
    try:
        if kind == "wayland":
            return await asyncio.to_thread(_capture_portal)
        if kind == "x11":
            return await asyncio.to_thread(_capture_x11)
    except UnavailableError:
        raise
    except Exception as exc:
        log.warning("screen_capture_failed", session=kind, error=type(exc).__name__)
        raise UnavailableError(f"Capture d'écran impossible ({type(exc).__name__}).") from exc
    raise UnavailableError("Aucun écran à capturer (ni Wayland ni X11).")
