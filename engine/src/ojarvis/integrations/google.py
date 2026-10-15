"""Google Agenda : connexion OAuth « Desktop app », puis serveur MCP.

Connexion (Réglages → Intégrations → Google Agenda) :
1. le moteur ouvre un petit serveur sur `http://127.0.0.1:<port au hasard>` ;
2. ton navigateur affiche la page de consentement de Google ; tu acceptes ;
3. Google renvoie vers ce serveur local un code, échangé contre un jeton (PKCE, état
   vérifié) ; le jeton de rafraîchissement va dans le trousseau, jamais ailleurs.

Serveur MCP : celui de Google (`calendarmcp.googleapis.com`, en préversion, à activer dans
ton projet Google Cloud) quand il répond ; sinon celui de Jarvis (`calendar_server.py`),
qui parle à l'API Google Agenda.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import secrets
import time
from collections.abc import AsyncGenerator, Callable
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

from ojarvis.core.errors import InvalidInputError, UnavailableError, UpstreamError
from ojarvis.core.logs import get_logger
from ojarvis.events.bus import EventBus
from ojarvis.security.redaction import REDACTOR
from ojarvis.security.secrets import SecretBackend

log = get_logger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - adresse, pas un secret
SCOPES = (
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
)
CALENDAR_MCP_URL = "https://calendarmcp.googleapis.com/mcp/v1"
TOKEN_KEY = "OJARVIS_GOOGLE_TOKEN"  # noqa: S105 - nom de l'entrée du trousseau
LOGIN_TIMEOUT_S = 600.0

_PAGE = (
    "<!doctype html><meta charset=utf-8><title>O-jarvis</title>"
    "<body style='font-family:sans-serif;background:#04060b;color:#e7eef8;padding:3rem'>"
    "<h1>{title}</h1><p>{text}</p></body>"
)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class GoogleAccount:
    def __init__(
        self,
        *,
        http: httpx.AsyncClient,
        secret: Callable[[str], str | None],
        backend: SecretBackend,
        bus: EventBus,
    ) -> None:
        self._http = http
        self._secret = secret
        self._backend = backend
        self._bus = bus
        self._access: tuple[str, float] | None = None
        self._login: _Login | None = None
        self.on_connected: Callable[[], Any] | None = None

    # ------------------------------------------------------------------ état

    def configured(self) -> bool:
        return bool(self._secret("GOOGLE_CLIENT_ID") and self._secret("GOOGLE_CLIENT_SECRET"))

    def _stored(self) -> dict[str, Any] | None:
        raw = self._backend.get(TOKEN_KEY)
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except ValueError:
            return None
        return data if isinstance(data, dict) and data.get("refresh_token") else None

    @property
    def connected(self) -> bool:
        return self._stored() is not None

    def load_into_redactor(self) -> None:
        stored = self._stored()
        if stored:
            REDACTOR.add_value(str(stored["refresh_token"]))

    # ------------------------------------------------------------------ connexion

    async def start_login(self) -> str:
        """Rend l'adresse de la page de consentement de Google (à ouvrir dans le navigateur)."""
        client_id = self._secret("GOOGLE_CLIENT_ID")
        if not (client_id and self._secret("GOOGLE_CLIENT_SECRET")):
            raise InvalidInputError(
                "Ajoute d'abord GOOGLE_CLIENT_ID et GOOGLE_CLIENT_SECRET (Réglages → clés).",
                code="google_not_configured",
            )
        if self._login is not None:
            await self._login.close()
        login = _Login(self)
        port = await login.open()
        self._login = login
        params = {
            "client_id": client_id,
            "redirect_uri": f"http://127.0.0.1:{port}",
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "code_challenge": login.challenge,
            "code_challenge_method": "S256",
            "state": login.state,
            "access_type": "offline",
            "prompt": "consent",
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    async def _exchange(self, code: str, redirect_uri: str, verifier: str) -> None:
        response = await self._http.post(
            TOKEN_URL,
            data={
                "client_id": self._secret("GOOGLE_CLIENT_ID") or "",
                "client_secret": self._secret("GOOGLE_CLIENT_SECRET") or "",
                "code": code,
                "code_verifier": verifier,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
            timeout=20.0,
        )
        if response.status_code != 200:
            raise UpstreamError(f"Google a refusé la connexion (HTTP {response.status_code}).")
        body = response.json()
        refresh = body.get("refresh_token")
        if not refresh:
            raise UpstreamError("Google n'a pas donné de jeton durable : réessaie la connexion.")
        REDACTOR.add_value(str(refresh))
        REDACTOR.add_value(str(body.get("access_token", "")))
        stored = {"refresh_token": refresh, "scope": body.get("scope", ""), "at": int(time.time())}
        await asyncio.to_thread(self._backend.set, TOKEN_KEY, json.dumps(stored))
        self._access = (
            str(body["access_token"]),
            time.monotonic() + int(body.get("expires_in", 3600)),
        )
        log.info("google_connected")
        await self._bus.publish("integration.google_connected", {})
        if self.on_connected is not None:
            await self.on_connected()

    async def access_token(self) -> str:
        if self._access is not None and self._access[1] - time.monotonic() > 60:
            return self._access[0]
        stored = self._stored()
        if stored is None:
            raise UnavailableError("Google Agenda n'est pas connecté (Réglages → Intégrations).")
        response = await self._http.post(
            TOKEN_URL,
            data={
                "client_id": self._secret("GOOGLE_CLIENT_ID") or "",
                "client_secret": self._secret("GOOGLE_CLIENT_SECRET") or "",
                "refresh_token": stored["refresh_token"],
                "grant_type": "refresh_token",
            },
            timeout=20.0,
        )
        if response.status_code != 200:
            raise UpstreamError(
                f"Google refuse de renouveler l'accès (HTTP {response.status_code}) : "
                "reconnecte Google Agenda."
            )
        body = response.json()
        token = str(body["access_token"])
        REDACTOR.add_value(token)
        self._access = (token, time.monotonic() + int(body.get("expires_in", 3600)))
        return token

    async def disconnect(self) -> None:
        stored = self._stored()
        self._access = None
        if stored is not None:
            with contextlib.suppress(httpx.HTTPError):
                await self._http.post(
                    "https://oauth2.googleapis.com/revoke",
                    data={"token": stored["refresh_token"]},
                    timeout=10.0,
                )
        await asyncio.to_thread(self._backend.delete, TOKEN_KEY)
        await self._bus.publish("integration.google_disconnected", {})

    async def close(self) -> None:
        if self._login is not None:
            await self._login.close()
            self._login = None

    # ------------------------------------------------------------------ MCP officiel

    def official_target(self) -> Any:
        """Le serveur MCP de Google, en HTTP, avec un jeton frais à chaque requête."""
        import httpx2  # noqa: PLC0415
        from mcp.client.streamable_http import streamable_http_client  # noqa: PLC0415

        account = self

        class Bearer(httpx2.Auth):
            async def async_auth_flow(
                self, request: httpx2.Request
            ) -> AsyncGenerator[httpx2.Request, httpx2.Response]:
                request.headers["Authorization"] = f"Bearer {await account.access_token()}"
                yield request

        client = httpx2.AsyncClient(auth=Bearer(), timeout=httpx2.Timeout(30, read=120))
        return streamable_http_client(CALENDAR_MCP_URL, http_client=client)


class _Login:
    """Le petit serveur local qui reçoit la réponse de Google (une seule fois, 10 min au plus)."""

    def __init__(self, account: GoogleAccount) -> None:
        self._account = account
        self.state = secrets.token_urlsafe(24)
        self.verifier = secrets.token_urlsafe(64)
        self.challenge = _b64(hashlib.sha256(self.verifier.encode()).digest())
        self._server: asyncio.Server | None = None
        self._timer: asyncio.Task[None] | None = None
        self.port = 0

    async def open(self) -> int:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        self._timer = asyncio.create_task(self._expire())
        return self.port

    async def _expire(self) -> None:
        await asyncio.sleep(LOGIN_TIMEOUT_S)
        await self.close()

    async def _respond(
        self, writer: asyncio.StreamWriter, status: str, title: str, text: str
    ) -> None:
        body = _PAGE.format(title=title, text=text).encode()
        writer.write(
            f"HTTP/1.1 {status}\r\nContent-Type: text/html; charset=utf-8\r\n"
            f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
            + body
        )
        with contextlib.suppress(Exception):
            await writer.drain()
        writer.close()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
        except (TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            writer.close()
            return
        target = head.decode("latin-1").split(" ", 2)[1] if b" " in head else "/"
        query = parse_qs(urlsplit(target).query)
        if query.get("state", [""])[0] != self.state:
            await self._respond(
                writer, "400 Bad Request", "Lien invalide", "Relance la connexion depuis Jarvis."
            )
            return
        if "error" in query or "code" not in query:
            await self._respond(
                writer, "200 OK", "Connexion annulée", "Rien n'a été partagé avec Jarvis."
            )
            await self.close()
            return
        try:
            await self._account._exchange(
                query["code"][0], f"http://127.0.0.1:{self.port}", self.verifier
            )
        except Exception as exc:
            log.warning("google_exchange_failed", error=type(exc).__name__)
            await self._respond(
                writer,
                "502 Bad Gateway",
                "Connexion impossible",
                "Google a refusé l'échange : réessaie.",
            )
            return
        await self._respond(
            writer, "200 OK", "Jarvis est connecté à Google Agenda", "Tu peux fermer cet onglet."
        )
        await self.close()

    async def close(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.close()
        timer, self._timer = self._timer, None
        if timer is not None and timer is not asyncio.current_task():
            timer.cancel()


async def attach_agenda(account: GoogleAccount, manager: Any, http: httpx.AsyncClient) -> str:
    """Branche Google Agenda : le serveur MCP de Google s'il répond, sinon celui de Jarvis."""
    from ojarvis.integrations.calendar_server import build_server  # noqa: PLC0415
    from ojarvis.integrations.connection import McpCallError  # noqa: PLC0415

    if not account.connected:
        manager.set_target("agenda", None)
        return "non connecté"
    manager.set_target("agenda", account.official_target, detail="serveur officiel de Google")
    try:
        await manager.ensure("agenda")
    except McpCallError:
        log.info("google_official_mcp_unavailable")
        server = build_server(http, account.access_token)
        manager.set_target(
            "agenda",
            lambda: server,
            detail="serveur de Jarvis (celui de Google n'est pas activé dans ton projet)",
        )
        await manager.ensure("agenda")
        return "jarvis"
    return "officiel"
