"""Flux d'événements vers l'interface (WebSocket).

Protocole : le client envoie d'abord `{"type": "auth", "token": "..."}` dans les 5 s.
Le serveur répond `{"type": "hello"}` puis pousse `{"type": "event", "event": {...}}`.
`{"type": "ping"}` reçoit `{"type": "pong"}`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

import anyio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ojarvis import __version__
from ojarvis.core.logs import get_logger
from ojarvis.events.bus import Event
from ojarvis.security.auth import token_matches
from ojarvis.services import Services

log = get_logger(__name__)
router = APIRouter(prefix="/v1")

AUTH_TIMEOUT_S = 5.0
CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN_ORIGIN = 4403


def _event_message(event: Event) -> str:
    return json.dumps({"type": "event", "event": event.model_dump(mode="json")}, ensure_ascii=False)


async def _close_quietly(websocket: WebSocket) -> None:
    with contextlib.suppress(RuntimeError, WebSocketDisconnect):
        await websocket.close(code=CLOSE_UNAUTHORIZED)


@router.websocket("/events/ws")
async def events_ws(websocket: WebSocket) -> None:
    services: Services = websocket.app.state.services
    token: str = websocket.app.state.token
    origin = websocket.headers.get("origin")
    if origin is not None and origin not in services.config.allowed_origins:
        await websocket.close(code=CLOSE_FORBIDDEN_ORIGIN)
        return
    await websocket.accept()
    try:
        first: dict[str, Any] = await asyncio.wait_for(websocket.receive_json(), AUTH_TIMEOUT_S)
    except WebSocketDisconnect:
        return  # le client est parti avant de s'authentifier : rien à fermer
    except (TimeoutError, ValueError, json.JSONDecodeError):
        await _close_quietly(websocket)
        return
    if first.get("type") != "auth" or not token_matches(token, str(first.get("token", ""))):
        await _close_quietly(websocket)
        return

    async with services.bus.stream("*") as queue:
        await websocket.send_text(json.dumps({"type": "hello", "version": __version__}))
        # Groupe de tâches anyio : quand l'une s'arrête (client parti, envoi impossible),
        # elle annule l'autre ; l'annulation venue de l'extérieur reste reconnue comme telle.
        async with anyio.create_task_group() as group:

            async def pump() -> None:
                try:
                    while True:
                        event = await queue.get()
                        await websocket.send_text(_event_message(event))
                except (WebSocketDisconnect, RuntimeError) as exc:
                    if isinstance(exc, RuntimeError):
                        log.warning("event_stream_closed", error_type=type(exc).__name__)
                finally:
                    group.cancel_scope.cancel()

            async def listen() -> None:
                try:
                    while True:
                        message = await websocket.receive_json()
                        if isinstance(message, dict) and message.get("type") == "ping":
                            await websocket.send_text('{"type":"pong"}')
                except (WebSocketDisconnect, ValueError, RuntimeError):
                    pass  # client parti, ou message illisible : on ferme le flux
                finally:
                    group.cancel_scope.cancel()

            group.start_soon(pump)
            group.start_soon(listen)
