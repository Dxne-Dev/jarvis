"""Google Agenda : connexion OAuth par redirection locale, puis serveur MCP (repli maison)."""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from anyio.from_thread import BlockingPortal
from fastapi.testclient import TestClient
from mcp import StdioServerParameters

from ojarvis.integrations.google import TOKEN_KEY, attach_agenda
from ojarvis.security.secrets import MemoryBackend
from ojarvis.services import Services

CLIENT_ID = "123-abc.apps.googleusercontent.com"
CLIENT_SECRET = "GOCSPX-" + "s" * 28  # construit à l'exécution
REFRESH = "1//0g" + "r" * 40
ACCESS = "ya29." + "a" * 60


def portal(client: TestClient) -> BlockingPortal:
    assert client.portal is not None
    return client.portal


@pytest.fixture
def google(client: TestClient, upstream: dict[str, Any]) -> list[dict[str, Any]]:
    exchanges: list[dict[str, Any]] = []

    def token(request: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        exchanges.append(form)
        if form.get("grant_type") == "authorization_code":
            return httpx.Response(
                200,
                json={
                    "access_token": ACCESS,
                    "refresh_token": REFRESH,
                    "expires_in": 3600,
                    "scope": "calendar",
                },
            )
        return httpx.Response(200, json={"access_token": ACCESS + "2", "expires_in": 3600})

    def calendar(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"].startswith("Bearer ya29.")
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "e1",
                            "summary": "Dentiste",
                            "location": "Cotonou",
                            "start": {"dateTime": "2026-10-16T09:00:00+02:00"},
                            "end": {"dateTime": "2026-10-16T09:30:00+02:00"},
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "e2",
                "summary": "Nouveau",
                "start": {"date": "2026-10-17"},
                "end": {"date": "2026-10-18"},
            },
        )

    upstream["oauth2.googleapis.com"] = token
    upstream["www.googleapis.com"] = calendar
    for name, value in (("GOOGLE_CLIENT_ID", CLIENT_ID), ("GOOGLE_CLIENT_SECRET", CLIENT_SECRET)):
        assert client.put(f"/v1/secrets/{name}", json={"value": value}).status_code == 204
    return exchanges


def test_the_oauth_login_checks_state_uses_pkce_and_keeps_the_token_in_the_keyring(
    client: TestClient, services: Services, google: list[dict[str, Any]], backend: MemoryBackend
) -> None:
    url = client.post("/v1/integrations/google/connect").json()["url"]
    params = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert params["client_id"] == CLIENT_ID
    assert params["redirect_uri"].startswith("http://127.0.0.1:")
    assert params["code_challenge_method"] == "S256"
    assert "calendar.events" in params["scope"]
    assert CLIENT_SECRET not in url

    # Une réponse avec un autre état (lien forgé) est refusée.
    forged = httpx.get(params["redirect_uri"], params={"code": "x", "state": "faux"})
    assert forged.status_code == 400
    assert backend.get(TOKEN_KEY) is None

    done = httpx.get(params["redirect_uri"], params={"code": "le-code", "state": params["state"]})
    assert done.status_code == 200
    assert "Jarvis est connecté à Google Agenda" in done.text
    exchange = google[0]
    assert exchange["code"] == "le-code"
    assert exchange["grant_type"] == "authorization_code"
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(exchange["code_verifier"].encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    assert challenge == params["code_challenge"]
    stored = json.loads(backend.get(TOKEN_KEY) or "{}")
    assert stored["refresh_token"] == REFRESH
    status = {s["name"]: s for s in client.get("/v1/integrations").json()}
    assert status["agenda"]["account_connected"] is True
    assert REFRESH not in json.dumps(status)

    assert client.post("/v1/integrations/google/disconnect").status_code == 200
    assert backend.get(TOKEN_KEY) is None


def test_without_app_keys_the_login_explains_what_is_missing(client: TestClient) -> None:
    response = client.post("/v1/integrations/google/connect")
    assert response.status_code == 422
    assert "GOOGLE_CLIENT_ID" in response.json()["error"]["message"]


def test_the_agenda_falls_back_to_jarvis_own_mcp_server(
    client: TestClient, services: Services, google: list[dict[str, Any]], backend: MemoryBackend
) -> None:
    backend.set(TOKEN_KEY, json.dumps({"refresh_token": REFRESH}))
    # Le serveur officiel de Google ne répond pas (pas activé dans le projet) : repli.
    services.google.official_target = lambda: StdioServerParameters(command="/bin/false")  # type: ignore[method-assign]
    mode = portal(client).call(attach_agenda, services.google, services.integrations, services.http)
    assert mode == "jarvis"
    tools = portal(client).call(services.integrations.ensure, "agenda")
    assert sorted(tools) == ["creer_evenement", "lister_evenements", "supprimer_evenement"]
    assert [int(tools[n].level) for n in sorted(tools)] == [2, 1, 3]
    text, is_error = portal(client).call(
        services.integrations.call, "agenda", "lister_evenements", {}
    )
    assert not is_error
    assert "16/10 09:00–09:30 Dentiste — Cotonou [id e1]" in text
    status = {s["name"]: s for s in client.get("/v1/integrations").json()}
    assert status["agenda"]["status"] == "prêt"
    assert "serveur de Jarvis" in status["agenda"]["detail"]
    # Le jeton d'accès a été obtenu par rafraîchissement, jamais exposé.
    assert google[-1]["grant_type"] == "refresh_token"
