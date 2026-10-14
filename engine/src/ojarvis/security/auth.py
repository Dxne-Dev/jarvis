"""Accès au moteur : jeton par lancement, hôte local uniquement, ID de corrélation."""

from __future__ import annotations

import hmac
import json
import re

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ojarvis.core.context import correlation_id_var, new_correlation_id
from ojarvis.core.errors import error_body

_CORRELATION_HEADER = b"x-correlation-id"
_VALID_CORRELATION = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def token_matches(expected: str, presented: str | None) -> bool:
    if not presented:
        return False
    return hmac.compare_digest(expected.encode(), presented.encode())


class CorrelationIdMiddleware:
    """Reprend l'ID fourni par l'interface ou en crée un, et le renvoie dans la réponse."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        provided = dict(scope.get("headers", [])).get(_CORRELATION_HEADER, b"").decode("latin-1")
        correlation_id = provided if _VALID_CORRELATION.match(provided) else new_correlation_id()
        token = correlation_id_var.set(correlation_id)
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((_CORRELATION_HEADER, correlation_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            structlog.contextvars.unbind_contextvars("correlation_id")
            correlation_id_var.reset(token)


class TokenAuthMiddleware:
    """Exige `Authorization: Bearer <jeton>` sur toutes les routes HTTP sauf les publiques.

    Les WebSocket s'authentifient dans leur premier message (un navigateur ne peut pas
    poser d'en-tête sur une WebSocket).
    """

    def __init__(self, app: ASGIApp, *, token: str, public_paths: frozenset[str]) -> None:
        self.app = app
        self._token = token
        self._public = public_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] == "OPTIONS" or scope["path"] in self._public:
            await self.app(scope, receive, send)
            return
        header = dict(scope.get("headers", [])).get(b"authorization", b"").decode("latin-1")
        presented = header[7:] if header[:7].lower() == "bearer " else None
        if token_matches(self._token, presented):
            await self.app(scope, receive, send)
            return
        body = json.dumps(error_body("unauthorized", "Jeton absent ou invalide.")).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
