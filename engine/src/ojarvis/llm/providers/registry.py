"""Construction des fournisseurs à partir du trousseau, et suivi du service Ollama local."""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx

from ojarvis.core.logs import get_logger
from ojarvis.llm.catalog import Catalog, openrouter_free_specs
from ojarvis.llm.providers.anthropic_provider import AnthropicProvider
from ojarvis.llm.providers.base import Provider
from ojarvis.llm.providers.openai_compat import (
    DEEPSEEK,
    META,
    OLLAMA,
    OPENAI,
    OPENROUTER,
    OpenAICompatibleProvider,
)
from ojarvis.security.secrets import SecretStore

log = get_logger(__name__)

OLLAMA_URL = "http://127.0.0.1:11434"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"


class OllamaProvider(OpenAICompatibleProvider):
    """Ollama n'a pas de clé : il est « configuré » s'il répond et possède des modèles."""

    def __init__(self, *, check_every_s: float = 60.0) -> None:
        super().__init__(OLLAMA, lambda: "ollama")
        self._models: list[str] = []
        self._checked_at = 0.0
        self._every = check_every_s
        self.reachable = False

    def is_configured(self) -> bool:
        return self.reachable and bool(self._models)

    @property
    def models(self) -> list[str]:
        return list(self._models)

    async def refresh(self, client: httpx.AsyncClient, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._checked_at < self._every:
            return
        self._checked_at = now
        try:
            response = await client.get(f"{OLLAMA_URL}/api/tags", timeout=2.0)
            response.raise_for_status()
            models = response.json().get("models", [])
            self._models = [str(m.get("name")) for m in models if isinstance(m, dict)]
            self.reachable = True
        except (httpx.HTTPError, ValueError):
            self.reachable = False
            self._models = []

    async def warm_up(
        self, client: httpx.AsyncClient, model: str, *, keep_alive: str = "10m"
    ) -> None:
        """Précharge le modèle en mémoire (le premier chargement prend des dizaines de secondes)."""
        try:
            await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": model, "keep_alive": keep_alive},
                timeout=180.0,
            )
        except httpx.HTTPError:
            log.warning("ollama_warm_up_failed", model=model)


def build_providers(secrets: SecretStore) -> dict[str, Provider]:
    def key(name: str) -> Callable[[], str | None]:
        return lambda: secrets.get(name)

    return {
        "deepseek": OpenAICompatibleProvider(DEEPSEEK, key("DEEPSEEK_API_KEY")),
        "anthropic": AnthropicProvider(key("ANTHROPIC_API_KEY")),
        "openai": OpenAICompatibleProvider(OPENAI, key("OPENAI_API_KEY")),
        "openrouter": OpenAICompatibleProvider(OPENROUTER, key("OPENROUTER_API_KEY")),
        "meta": OpenAICompatibleProvider(META, key("MODEL_API_KEY")),
        "ollama": OllamaProvider(),
    }


async def discover_openrouter_free(catalog: Catalog, client: httpx.AsyncClient) -> int:
    """Met à jour la liste des modèles gratuits d'OpenRouter (liste publique, sans clé)."""
    try:
        response = await client.get(OPENROUTER_MODELS_URL, timeout=15.0)
        response.raise_for_status()
        data = response.json().get("data", [])
    except (httpx.HTTPError, ValueError):
        log.warning("openrouter_discovery_failed")
        return 0
    specs = openrouter_free_specs([m for m in data if isinstance(m, dict)])
    if specs:
        catalog.replace_provider("openrouter", specs)
    return len(specs)
