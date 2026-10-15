"""Proxy local du navigateur de Jarvis : chaque connexion n'atteint qu'une adresse publique.

Le navigateur suit seul les redirections, et le filtrage de Playwright ne les voit pas :
une page publique pouvait donc rediriger vers la box ou un service local. Ici, toute
connexion (page, image, redirection, WebSocket) passe par ce proxy, qui résout le nom,
vérifie chaque adresse et se connecte lui-même à l'adresse vérifiée (pas de
« rebinding » DNS possible entre la vérification et la connexion).
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import socket
from urllib.parse import urlsplit

from ojarvis.core.logs import get_logger

log = get_logger(__name__)

HEAD_TIMEOUT_S = 30.0
CONNECT_TIMEOUT_S = 15.0
_HOP_HEADERS = ("proxy-connection:", "connection:", "keep-alive:", "proxy-authorization:")


class BlockedAddressError(Exception):
    pass


def _split_host_port(target: str, default_port: int) -> tuple[str, int]:
    if target.startswith("["):
        host, _, rest = target[1:].partition("]")
        port = rest.removeprefix(":")
    else:
        host, _, port = target.rpartition(":") if target.count(":") == 1 else (target, "", "")
    return host.lower(), int(port) if port else default_port


class GuardProxy:
    def __init__(self, *, allowed_hosts: tuple[str, ...] = ()) -> None:
        self._allowed_hosts = allowed_hosts
        self._server: asyncio.Server | None = None
        self.port = 0
        self.blocked = 0

    async def start(self) -> int:
        if self._server is None:
            self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
            self.port = self._server.sockets[0].getsockname()[1]
        return self.port

    async def close(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.close()
            with contextlib.suppress(Exception):
                await server.wait_closed()

    async def resolve(self, host: str, port: int) -> str:
        """Adresse IP à joindre, seulement si toutes celles du nom sont publiques."""
        if not host:
            raise BlockedAddressError("adresse vide")
        loop = asyncio.get_running_loop()
        try:
            infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise BlockedAddressError("nom introuvable") from exc
        addresses = [str(info[4][0]) for info in infos]
        if not addresses:
            raise BlockedAddressError("nom introuvable")
        if host not in self._allowed_hosts:
            if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
                raise BlockedAddressError("adresse locale")
            if not all(ipaddress.ip_address(a.split("%")[0]).is_global for a in addresses):
                raise BlockedAddressError("adresse privée ou locale")
        return addresses[0]

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        upstream: asyncio.StreamWriter | None = None
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), HEAD_TIMEOUT_S)
            lines = head.decode("latin-1").split("\r\n")
            method, target, version = lines[0].split(" ", 2)
            if method == "CONNECT":
                host, port = _split_host_port(target, 443)
                address = await self.resolve(host, port)
                up_reader, up_writer = await asyncio.wait_for(
                    asyncio.open_connection(address, port), CONNECT_TIMEOUT_S
                )
                upstream = up_writer
                writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                await writer.drain()
            else:
                parts = urlsplit(target)
                if parts.scheme != "http" or not parts.hostname:
                    raise BlockedAddressError("requête de proxy invalide")
                host, port = parts.hostname.lower(), parts.port or 80
                address = await self.resolve(host, port)
                up_reader, up_writer = await asyncio.wait_for(
                    asyncio.open_connection(address, port), CONNECT_TIMEOUT_S
                )
                upstream = up_writer
                path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
                headers = [h for h in lines[1:] if h and not h.lower().startswith(_HOP_HEADERS)]
                # Une requête par connexion : la suivante, peut-être vers un autre hôte,
                # repassera par la vérification.
                request = "\r\n".join([f"{method} {path} {version}", *headers, "Connection: close"])
                up_writer.write(request.encode("latin-1") + b"\r\n\r\n")
                await up_writer.drain()
            await _pipe_both(reader, writer, up_reader, up_writer)
        except BlockedAddressError as exc:
            self.blocked += 1
            log.warning("browser_request_blocked", reason=str(exc))
            with contextlib.suppress(Exception):
                writer.write(
                    b"HTTP/1.1 403 Forbidden\r\nContent-Type: text/plain; charset=utf-8\r\n"
                    b"Connection: close\r\n\r\n"
                    + "Adresse refusée par le navigateur de Jarvis.".encode()
                )
                await writer.drain()
        except (OSError, ValueError, TimeoutError, asyncio.IncompleteReadError):
            with contextlib.suppress(Exception):
                writer.write(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
                await writer.drain()
        finally:
            for stream in (writer, upstream):
                if stream is not None:
                    with contextlib.suppress(Exception):
                        stream.close()


async def _copy(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    with contextlib.suppress(Exception):
        while chunk := await reader.read(65536):
            writer.write(chunk)
            await writer.drain()
    with contextlib.suppress(Exception):
        if writer.can_write_eof():
            writer.write_eof()


async def _pipe_both(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    up_reader: asyncio.StreamReader,
    up_writer: asyncio.StreamWriter,
) -> None:
    """Relaie dans les deux sens ; s'arrête quand le serveur a fini de répondre."""
    upload = asyncio.create_task(_copy(client_reader, up_writer))
    try:
        await _copy(up_reader, client_writer)
    finally:
        upload.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await upload
