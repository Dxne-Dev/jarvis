"""Quand un fournisseur en ligne tombe, le modèle local est chargé en mémoire à l'avance."""

from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from ojarvis.core.clock import utc_now
from ojarvis.events.bus import Event
from ojarvis.llm.providers.registry import OllamaProvider
from ojarvis.services import LOCAL_MODEL, Services


class RecordingOllama(OllamaProvider):
    def __init__(self, models: list[str]) -> None:
        super().__init__()
        self._installed = models
        self.warmed: list[str] = []

    async def refresh(self, client: httpx.AsyncClient, *, force: bool = False) -> None:
        del client, force
        self._models = list(self._installed)
        self.reachable = True

    async def warm_up(
        self, client: httpx.AsyncClient, model: str, *, keep_alive: str = "10m"
    ) -> None:
        del client, keep_alive
        self.warmed.append(model)


def degraded(provider: str) -> Event:
    return Event(
        type="llm.provider_degraded",
        ts=utc_now(),
        source="llm",
        correlation_id=None,
        payload={"provider": provider},
    )


def test_local_model_is_preloaded_once_when_deepseek_goes_down(
    client: TestClient, services: Services
) -> None:
    ollama = RecordingOllama([LOCAL_MODEL])
    services.providers["ollama"] = ollama
    portal = client.portal
    assert portal is not None
    portal.call(services._preload_local_model, degraded("deepseek"))
    portal.call(services._preload_local_model, degraded("openrouter"))
    assert ollama.warmed == [LOCAL_MODEL]  # au plus une fois toutes les 5 minutes


def test_no_preload_when_ollama_itself_fails_or_lacks_the_model(
    client: TestClient, services: Services
) -> None:
    portal = client.portal
    assert portal is not None
    absent = RecordingOllama(["autre-modele"])
    services.providers["ollama"] = absent
    portal.call(services._preload_local_model, degraded("deepseek"))
    assert absent.warmed == []
    services._last_local_preload = -1e9
    present = RecordingOllama([LOCAL_MODEL])
    services.providers["ollama"] = present
    portal.call(services._preload_local_model, degraded("ollama"))
    assert present.warmed == []
