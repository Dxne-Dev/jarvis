from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from ojarvis.app import create_app
from ojarvis.config import TAURI_ORIGINS, EngineConfig, resolve_paths
from ojarvis.security.redaction import REDACTOR
from ojarvis.security.secrets import MemoryBackend
from ojarvis.services import Services

TOKEN = "t" * 40
DEV_ORIGIN = "http://localhost:1420"


@pytest.fixture(autouse=True)
def _reset_redactor() -> Iterator[None]:
    REDACTOR.set_values([])
    yield
    REDACTOR.set_values([])


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path / "home"


@pytest.fixture
def config(home: Path) -> EngineConfig:
    return EngineConfig(
        paths=resolve_paths({"OJARVIS_HOME": str(home)}),
        dev_mode=True,
        dotenv_path=None,
        allowed_origins=(*TAURI_ORIGINS, DEV_ORIGIN),
        allowed_hosts=("testserver", "127.0.0.1", "localhost"),
    )


@pytest.fixture
def backend() -> MemoryBackend:
    return MemoryBackend()


Router = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def upstream() -> dict[str, Router]:
    """Réponses simulées des fournisseurs, par hôte."""
    return {}


@pytest.fixture
def client(
    config: EngineConfig, backend: MemoryBackend, upstream: dict[str, Router]
) -> Iterator[TestClient]:
    def handler(request: httpx.Request) -> httpx.Response:
        route = upstream.get(request.url.host)
        if route is None:
            return httpx.Response(599, json={"error": "hôte non simulé"})
        return route(request)

    app = create_app(
        config,
        token=TOKEN,
        secret_backend=backend,
        http_transport=httpx.MockTransport(handler),
    )
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as test_client:
        yield test_client


@pytest.fixture
def services(client: TestClient) -> Services:
    result: Services = client.app.state.services  # type: ignore[attr-defined]
    return result
