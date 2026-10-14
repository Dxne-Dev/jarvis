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

        async def pump() -> None:
            while True:
                event = await queue.get()
                await websocket.send_text(_event_message(event))

        async def listen() -> None:
            while True:
                message = await websocket.receive_json()
                if isinstance(message, dict) and message.get("type") == "ping":
                    await websocket.send_text('{"type":"pong"}')

        tasks = [asyncio.create_task(pump()), asyncio.create_task(listen())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                # Lire l'exception d'une tâche annulée lèverait CancelledError.
                if task.cancelled():
                    continue
                exc = task.exception()
                if exc is not None and not isinstance(exc, WebSocketDisconnect):
                    log.warning("event_stream_closed", error_type=type(exc).__name__)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
