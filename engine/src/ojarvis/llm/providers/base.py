"""Interface commune des fournisseurs de modèles."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from ojarvis.llm.types import LLMRequest, StreamEvent


class Provider(Protocol):
    #: Identifiant court : deepseek, openrouter, ollama, openai, anthropic, fake.
    name: str
    #: Vrai pour un modèle qui tourne sur la machine (données sensibles, hors ligne).
    local: bool

    def is_configured(self) -> bool:
        """Vrai si le fournisseur peut être appelé (clé présente, ou service local)."""
        ...

    def stream(self, request: LLMRequest, model: str) -> AsyncIterator[StreamEvent]:
        """Flux d'événements. Lève une `LLMError` classée en cas d'échec."""
        ...

    async def list_models(self) -> list[str]: ...
