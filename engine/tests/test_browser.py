"""Navigateur de Jarvis : coffre chiffré, import de cookies, proxy de garde.

Le vrai navigateur, sur un site local, est dans `test_browser_pages.py`.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ojarvis.browser.cookies import (
    decrypt_value,
    derive_key,
    encrypt_value,
    find_sources,
    read_cookies,
)
from ojarvis.browser.proxy import GuardProxy
from ojarvis.browser.vault import CookieVault, filter_state, normalize_domain, parents, related
from ojarvis.core.errors import InvalidInputError
from ojarvis.services import Services

PASSWORD = b"mot-de-passe-du-trousseau"


# ---------------------------------------------------------------------- domaines et coffre


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("github.com", "github.com"),
        ("https://www.GitHub.com/settings", "github.com"),
        (".mail.google.com", "mail.google.com"),
        ("exemple.fr:8443", "exemple.fr"),
    ],
)
def test_domains_are_normalized(raw: str, expected: str) -> None:
    assert normalize_domain(raw) == expected


@pytest.mark.parametrize("raw", ["", "localhost", "127.0.0.1", "un domaine", "a..b", "-x.com"])
def test_odd_domains_are_refused(raw: str) -> None:
    with pytest.raises(InvalidInputError):
        normalize_domain(raw)


def test_cookie_relations() -> None:
    assert related(".google.com", "mail.google.com")  # parent utile à la connexion
    assert related("api.github.com", "github.com")
    assert not related("evilgithub.com", "github.com")
    assert parents("mail.google.com") == ["mail.google.com", "google.com"]
    state = {
        "cookies": [{"name": "a", "domain": ".github.com"}, {"name": "b", "domain": "evil.com"}],
        "origins": [
            {"origin": "https://github.com", "localStorage": []},
            {"origin": "https://evil.com"},
        ],
    }
    kept = filter_state(state, ["github.com"])
    assert [c["name"] for c in kept["cookies"]] == ["a"]
    assert len(kept["origins"]) == 1


def test_the_vault_is_encrypted_and_per_domain(tmp_path: Path) -> None:
    vault = CookieVault(tmp_path / "coffre.bin", lambda: "cle-locale")
    vault.merge(
        [
            {"name": "session", "value": "SECRET-123", "domain": ".github.com", "path": "/"},
            {"name": "sid", "value": "AUTRE-456", "domain": "exemple.fr", "path": "/"},
        ]
    )
    raw = (tmp_path / "coffre.bin").read_bytes()
    assert b"SECRET-123" not in raw
    assert b"github" not in raw
    assert oct((tmp_path / "coffre.bin").stat().st_mode & 0o777) == "0o600"
    assert vault.domains() == {"github.com", "exemple.fr"}
    vault.merge([{"name": "session", "value": "NOUVEAU", "domain": ".github.com", "path": "/"}])
    assert vault.count("github.com") == 1
    assert vault.remove_domain("github.com") == 1
    assert vault.domains() == {"exemple.fr"}
    # Autre clé locale (trousseau réinitialisé) : rien de lisible, mais pas de plantage.
    assert CookieVault(tmp_path / "coffre.bin", lambda: "autre").load()["cookies"] == []


# ---------------------------------------------------------------------- import depuis Chrome


def make_profile(home: Path, *, meta_version: int = 24) -> Path:
    root = home / ".config" / "google-chrome"
    profile = root / "Default" / "Network"
    profile.mkdir(parents=True)
    (root / "Local State").write_text(
        json.dumps({"profile": {"info_cache": {"Default": {"name": "Perso"}}}}), encoding="utf-8"
    )
    path = profile / "Cookies"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE meta (key TEXT, value TEXT)")
    db.execute("INSERT INTO meta VALUES ('version', ?)", (str(meta_version),))
    db.execute(
        "CREATE TABLE cookies (host_key TEXT, name TEXT, value TEXT, encrypted_value BLOB, "
        "path TEXT, expires_utc INTEGER, is_secure INTEGER, is_httponly INTEGER, samesite INTEGER)"
    )

    def add(host: str, name: str, plain: str, *, prefix: bytes | None, key: bytes = b"") -> None:
        value, encrypted = plain, b""
        if prefix is not None:
            payload = plain.encode()
            if meta_version >= 24:
                payload = hashlib.sha256(host.encode()).digest() + payload
            value, encrypted = "", encrypt_value(payload, key, prefix)
        db.execute(
            "INSERT INTO cookies VALUES (?, ?, ?, ?, '/', 13400000000000000, 1, 1, 0)",
            (host, name, value, encrypted),
        )

    add(".github.com", "logged_in", "yes", prefix=b"v10", key=derive_key(b"peanuts"))
    add("github.com", "user_session", "SESSION-v11", prefix=b"v11", key=derive_key(PASSWORD))
    add("api.github.com", "clair", "valeur-claire", prefix=None)
    add(".evilgithub.com", "piege", "x", prefix=b"v10", key=derive_key(b"peanuts"))
    add(".google.com", "autre", "y", prefix=b"v10", key=derive_key(b"peanuts"))
    db.commit()
    db.close()
    return path


def test_chrome_cookies_of_one_domain_are_decrypted(tmp_path: Path) -> None:
    make_profile(tmp_path)
    [source] = find_sources(tmp_path)
    assert source.id == "chrome:Default"
    assert source.label == "Google Chrome — Perso"
    cookies = read_cookies(source, "github.com", password=PASSWORD)
    values = {c["name"]: c["value"] for c in cookies}
    assert values == {"logged_in": "yes", "user_session": "SESSION-v11", "clair": "valeur-claire"}
    session = next(c for c in cookies if c["name"] == "user_session")
    assert session["secure"]
    assert session["httpOnly"]
    assert session["sameSite"] == "None"
    assert session["expires"] == pytest.approx(13400000000000000 / 1e6 - 11644473600)


def test_old_schema_and_wrong_password(tmp_path: Path) -> None:
    make_profile(tmp_path, meta_version=18)
    [source] = find_sources(tmp_path)
    cookies = read_cookies(source, "github.com", password=b"faux")
    # Le cookie v11 reste illisible avec un mauvais mot de passe : il n'est pas importé.
    assert {c["name"] for c in cookies} == {"logged_in", "clair"}
    key = derive_key(b"peanuts")
    assert (
        decrypt_value(b"v99" + b"x" * 16, keys={b"v10": [key]}, host_key="a", meta_version=24)
        is None
    )


# ---------------------------------------------------------------------- autorisations par l'API


def test_import_and_revoke_through_the_api(
    client: TestClient, services: Services, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = services.config.user_home
    assert home is not None
    make_profile(home)
    monkeypatch.setattr("ojarvis.browser.service.safe_storage_password", lambda app: PASSWORD)
    state = client.get("/v1/browser").json()
    assert state["sources"] == [{"id": "chrome:Default", "label": "Google Chrome — Perso"}]
    assert state["grants"] == []

    imported = client.post(
        "/v1/browser/cookies", json={"source": "chrome:Default", "domain": "www.github.com"}
    )
    assert imported.status_code == 200
    assert imported.json()["domain"] == "github.com"
    assert imported.json()["count"] == 3
    assert services.browser.session.uses_identity("https://github.com/notifications")
    assert not services.browser.session.uses_identity("https://evilgithub.com/")
    vault = services.config.paths.data_dir / "navigateur" / "coffre.bin"
    assert vault.exists()
    assert b"SESSION-v11" not in vault.read_bytes()

    missing = client.post(
        "/v1/browser/cookies", json={"source": "chrome:Default", "domain": "absent.org"}
    )
    assert missing.status_code == 404
    assert client.delete("/v1/browser/cookies/github.com").status_code == 204
    assert client.get("/v1/browser").json()["grants"] == []
    assert not services.browser.session.uses_identity("https://github.com/")
    assert client.delete("/v1/browser/cookies/github.com").status_code == 404
    actions = [i["action"] for i in reversed(client.get("/v1/audit").json()["items"])]
    assert actions == ["navigateur.cookies_importes", "navigateur.cookies_revoques"]


def test_a_login_keeps_only_the_chosen_domain(
    client: TestClient, services: Services, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = services.browser.session
    opened: list[str] = []

    async def fake_start(url: str, on_closed: Any = None) -> None:
        opened.append(url)

    async def fake_finish() -> dict[str, Any]:
        return {
            "cookies": [
                {"name": "sid", "value": "S", "domain": ".exemple.fr", "path": "/"},
                {"name": "pub", "value": "T", "domain": ".regie-pub.com", "path": "/"},
            ],
            "origins": [],
        }

    monkeypatch.setattr(session, "login_start", fake_start)
    monkeypatch.setattr(session, "login_finish", fake_finish)
    assert client.post("/v1/browser/login", json={"url": "exemple.fr"}).json() == {
        "domain": "exemple.fr"
    }
    assert opened == ["https://exemple.fr"]
    grant = client.post("/v1/browser/login/finish").json()
    assert grant["domain"] == "exemple.fr"
    assert grant["source"] == "connexion"
    assert grant["count"] == 1
    vault = CookieVault(
        services.config.paths.data_dir / "navigateur" / "coffre.bin",
        lambda: services.secrets.get("OJARVIS_LOCAL_KEY"),
    )
    assert vault.domains() == {"exemple.fr"}  # la régie publicitaire n'est pas gardée
    assert client.get("/v1/audit").json()["items"][0]["action"] == "navigateur.connexion"


# ---------------------------------------------------------------------- proxy de garde


@pytest.fixture
async def origin() -> AsyncIterator[int]:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    yield server.sockets[0].getsockname()[1]
    server.close()


async def ask(port: int, request: bytes) -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(request)
    await writer.drain()
    data = await asyncio.wait_for(reader.read(65536), 5)
    writer.close()
    return data


async def test_the_proxy_only_reaches_allowed_or_public_addresses(origin: int) -> None:
    proxy = GuardProxy(allowed_hosts=("127.0.0.1",))
    port = await proxy.start()
    try:
        ok = await ask(port, f"GET http://127.0.0.1:{origin}/ HTTP/1.1\r\nHost: x\r\n\r\n".encode())
        assert ok.startswith(b"HTTP/1.1 200")
        assert ok.endswith(b"ok")
        for target in (f"127.0.0.2:{origin}", f"localhost:{origin}", "192.168.1.1:80", "[::1]:80"):
            blocked = await ask(port, f"GET http://{target}/ HTTP/1.1\r\nHost: x\r\n\r\n".encode())
            assert blocked.startswith(b"HTTP/1.1 403"), target
        tunnel = await ask(port, b"CONNECT 10.0.0.1:443 HTTP/1.1\r\nHost: 10.0.0.1:443\r\n\r\n")
        assert tunnel.startswith(b"HTTP/1.1 403")
        assert proxy.blocked == 5

        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(f"CONNECT 127.0.0.1:{origin} HTTP/1.1\r\n\r\n".encode())
        assert (await reader.readuntil(b"\r\n\r\n")).startswith(b"HTTP/1.1 200")
        writer.write(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
        assert (await asyncio.wait_for(reader.read(65536), 5)).endswith(b"ok")
        writer.close()
    finally:
        await proxy.close()
