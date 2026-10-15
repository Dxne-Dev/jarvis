"""Fournisseur de test déterministe : réponses scénarisées, latence simulée, pannes à la demande."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field

from ojarvis.llm.errors import LLMError
from ojarvis.llm.types import (
    LLMRequest,
    ReasoningDelta,
    StreamEnd,
    StreamEvent,
    TextDelta,
    ToolCall,
    ToolCallReady,
    Usage,
)


@dataclass
class FakeReply:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    reasoning: str = ""
    #: Erreur levée avant le premier morceau (repli possible) ou après (`fail_after_text`).
    error: LLMError | None = None
    fail_after_text: bool = False


Script = Callable[[LLMRequest], FakeReply]


def echo_script(request: LLMRequest) -> FakeReply:
    last = next((m.content for m in reversed(request.messages) if m.role == "user"), "")
    return FakeReply(text=f"Réponse de test : {last}")


class FakeProvider:
    local = False

    def __init__(
        self,
        name: str = "fake",
        script: Script = echo_script,
        *,
        delay_s: float = 0.0,
        chunk_chars: int = 12,
        configured: bool = True,
        local: bool = False,
    ) -> None:
        self.name = name
        self.local = local
        self._script = script
        self._delay = delay_s
        self._chunk = chunk_chars
        self._configured = configured
        self.requests: list[tuple[LLMRequest, str]] = []

    def is_configured(self) -> bool:
        return self._configured

    async def stream(self, request: LLMRequest, model: str) -> AsyncIterator[StreamEvent]:
        self.requests.append((request, model))
        reply = self._script(request)
        if reply.error is not None and not reply.fail_after_text:
            raise reply.error
        if self._delay:
            await asyncio.sleep(self._delay)
        if reply.reasoning:
            yield ReasoningDelta(reply.reasoning)
        for i in range(0, len(reply.text), self._chunk):
            yield TextDelta(reply.text[i : i + self._chunk])
            if self._delay:
                await asyncio.sleep(self._delay / 10)
        if reply.error is not None:
            raise reply.error
        for call in reply.tool_calls:
            yield ToolCallReady(call)
        words = sum(len(m.content.split()) for m in request.messages)
        yield StreamEnd(
            Usage(input_tokens=words * 2, output_tokens=max(1, len(reply.text.split()) * 2)),
            "tool_calls" if reply.tool_calls else "stop",
        )

    async def list_models(self) -> list[str]:
        return ["fake-model"]


def e2e_script(request: LLMRequest) -> FakeReply:
    """Réponses prévisibles pour les tests de bout en bout (mode développement uniquement)."""
    if request.tools and request.tools[0].name == "repondre":
        return FakeReply(tool_calls=[ToolCall("e2e", "repondre", {"faits": []})])
    system = request.messages[0].content if request.messages else ""
    if "titre" in system:
        return FakeReply(text="Conversation de test")
    last = next((m.content for m in reversed(request.messages) if m.role == "user"), "")
    return FakeReply(text=f"Bien reçu : **{last}**. Je suis la réponse de test de Jarvis.")
