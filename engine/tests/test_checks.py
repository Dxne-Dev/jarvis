"""Tests de contrat des vérifications de clés, contre des réponses simulées."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from ojarvis.db.engine import Database
from ojarvis.db.migrate import upgrade_to_head
from ojarvis.providers.checks import CHECKS, run_check
from ojarvis.security.secrets import CATALOG, MemoryBackend, SecretStore

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def store(tmp_path: Path) -> SecretStore:
    db_path = tmp_path / "c.db"
    upgrade_to_head(db_path)
    secret_store = SecretStore(Database(db_path), MemoryBackend())
    for spec in CATALOG:
        value = "123456789" if spec.name == "TELEGRAM_ALLOWED_USER_ID" else f"valeur-{spec.name}"
        secret_store.set(spec.name, value)
    return secret_store


def client_for(handler: Handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_every_catalog_entry_has_a_check() -> None:
    assert set(CHECKS) == {spec.name for spec in CATALOG}


OK_RESPONSES: dict[str, tuple[str, dict[str, object], str]] = {
    "DEEPSEEK_API_KEY": (
        "api.deepseek.com",
        {"data": [{"id": "deepseek-flash"}]},
        "deepseek-flash",
    ),
    "OPENROUTER_API_KEY": ("openrouter.ai", {"data": {"is_free_tier": True}}, "gratuite"),
    "OPENAI_API_KEY": ("api.openai.com", {"data": []}, "acceptée"),
    "ANTHROPIC_API_KEY": ("api.anthropic.com", {"data": []}, "acceptée"),
    "CARTESIA_API_KEY": ("api.cartesia.ai", {"data": [{"id": "v1"}, {"id": "v2"}]}, "2 voix"),
    "TAVILY_API_KEY": (
        "api.tavily.com",
        {"account": {"plan_usage": 3, "plan_limit": 1000}},
        "3 / 1000",
    ),
    "GITHUB_TOKEN": ("api.github.com", {"login": "octavebahoun"}, "octavebahoun"),
    "NOTION_TOKEN": ("api.notion.com", {"bot": {"workspace_name": "Espace"}}, "Espace"),
    "TELEGRAM_BOT_TOKEN": (
        "api.telegram.org",
        {"result": {"username": "ojarvi_bot"}},
        "@ojarvi_bot",
    ),
}


@pytest.mark.parametrize("name", sorted(OK_RESPONSES))
async def test_check_ok(name: str, store: SecretStore) -> None:
    host, body, expected = OK_RESPONSES[name]
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.url.host == host
        return httpx.Response(200, json=body)

    async with client_for(handler) as client:
        result = await run_check(name, store, client)
    assert result.ok, result.detail
    assert expected in result.detail
    assert result.latency_ms is not None
    assert len(seen) == 1


@pytest.mark.parametrize("name", sorted(OK_RESPONSES))
@pytest.mark.parametrize(
    ("status", "message"),
    [(401, "refusée"), (403, "refusée"), (429, "limite"), (500, "HTTP 500")],
)
async def test_check_http_errors(name: str, status: int, message: str, store: SecretStore) -> None:
    async with client_for(lambda r: httpx.Response(status, json={})) as client:
        result = await run_check(name, store, client)
    assert not result.ok
    assert message in result.detail


async def test_check_network_errors(store: SecretStore) -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("lent", request=request)

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("hors ligne", request=request)

    async with client_for(timeout) as client:
        assert "à temps" in (await run_check("DEEPSEEK_API_KEY", store, client)).detail
    async with client_for(down) as client:
        assert "réseau" in (await run_check("GITHUB_TOKEN", store, client)).detail
        assert "injoignable" in (await run_check("TELEGRAM_BOT_TOKEN", store, client)).detail


async def test_google_check(store: SecretStore) -> None:
    replies = {
        "invalid_grant": True,
        "invalid_client": False,
        "unauthorized_client": False,
        "autre": False,
    }
    for error, ok in replies.items():

        def reply(_: httpx.Request, e: str = error) -> httpx.Response:
            return httpx.Response(400, json={"error": e})

        async with client_for(reply) as client:
            result = await run_check("GOOGLE_CLIENT_SECRET", store, client)
        assert result.ok is ok, error


async def test_google_needs_both_values(store: SecretStore) -> None:
    store.delete("GOOGLE_CLIENT_SECRET")
    async with client_for(lambda r: httpx.Response(400, json={})) as client:
        result = await run_check("GOOGLE_CLIENT_ID", store, client)
    assert not result.ok
    assert "secret" in result.detail


async def test_telegram_user_id(store: SecretStore) -> None:
    async with client_for(lambda r: httpx.Response(500)) as client:
        assert (await run_check("TELEGRAM_ALLOWED_USER_ID", store, client)).ok
        store.set("TELEGRAM_ALLOWED_USER_ID", "pas-un-nombre")
        assert not (await run_check("TELEGRAM_ALLOWED_USER_ID", store, client)).ok


async def test_non_json_body_is_tolerated(store: SecretStore) -> None:
    async with client_for(lambda r: httpx.Response(200, text="<html>")) as client:
        result = await run_check("NOTION_TOKEN", store, client)
    assert result.ok
    assert "inconnu" in result.detail
