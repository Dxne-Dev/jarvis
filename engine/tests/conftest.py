from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from ojarvis.app import create_app
from ojarvis.config import TAURI_ORIGINS, EngineConfig, resolve_paths
from ojarvis.llm.providers.fake import FakeProvider
from ojarvis.memory.embeddings import HashEmbedder
from ojarvis.security.redaction import REDACTOR
from ojarvis.security.secrets import MemoryBackend
from ojarvis.services import Services
from ojarvis.shell.machine import MachineMap

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
        user_home=home / "perso",
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
def llm() -> dict[str, FakeProvider]:
    """Fournisseurs simulés ; un test peut remplacer leur script de réponse."""
    return {
        "deepseek": FakeProvider("deepseek"),
        "openrouter": FakeProvider("openrouter", configured=False),
        "ollama": FakeProvider("ollama", configured=False, local=True),
    }


@pytest.fixture
def client(
    config: EngineConfig,
    backend: MemoryBackend,
    upstream: dict[str, Router],
    llm: dict[str, FakeProvider],
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
        embedder=HashEmbedder(),
        providers=dict(llm),
        discover=False,
    )
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as test_client:
        # La carte de la machine n'est jamais relevée sur la machine qui lance les tests.
        test_client.app.state.services.machine._collect = fake_machine  # type: ignore[attr-defined]
        # Les fournisseurs simulés sont ceux du profil « Auto » ; « Tout Meta » a ses tests.
        test_client.patch("/v1/settings", json={"model_profile": "auto"}).raise_for_status()
        yield test_client


def fake_machine(home: Path) -> MachineMap:
    del home
    return MachineMap(
        hardware="Matériel : processeur de test (4 fils), mémoire 7,2 Go, échange 2 Go.",
        system="Système : Ubuntu 26.04 LTS, noyau 7.0.0, bureau GNOME (wayland).",
        disks="Disques : / (ext4) 457 Go, 392 Go utilisés (91 %), 43 Go libres.",
        tools="Outils : docker 28.1.1, node 22.11.0, python3 3.14.0, git 2.51.0.",
        services="Services : 40 en marche, dont NetworkManager, snapd ; arrêtés : docker.",
        projects="Projets (dossiers git, les plus récents d'abord) : ~/projet.",
    )


@pytest.fixture
def services(client: TestClient) -> Services:
    result: Services = client.app.state.services  # type: ignore[attr-defined]
    return result


# Un faux menu d'applications (fichiers .desktop), pour le contrôle du PC.
ENTRY = """[Desktop Entry]
Type=Application
Name={name}
{extra}
Exec={exec}
"""


def write_app(folder: Path, app_id: str, name: str, exec_: str, extra: str = "") -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{app_id}.desktop").write_text(
        ENTRY.format(name=name, exec=exec_, extra=extra), encoding="utf-8"
    )


@pytest.fixture
def menu(tmp_path: Path) -> Path:
    folder = tmp_path / "applications"
    write_app(
        folder,
        "org.gnome.Calculator",
        "Calculator",
        "gnome-calculator %U",
        "Name[fr]=Calculatrice\nKeywords=calcul;maths;",
    )
    write_app(folder, "firefox", "Firefox", "env MOZ_ENABLE_WAYLAND=1 /usr/lib/firefox/firefox %u")
    write_app(folder, "cache", "Caché", "cache", "NoDisplay=true")
    write_app(folder, "kde-only", "KDE seulement", "kde", "OnlyShowIn=KDE;")
    write_app(
        folder,
        "org.gnome.TextEditor",
        "Text Editor",
        "gnome-text-editor",
        "Name[fr]=Éditeur de texte",
    )
    return folder
