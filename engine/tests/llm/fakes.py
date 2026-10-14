"""Faux clients des SDK officiels, pour les tests de contrat des adaptateurs."""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any


def chunk(
    content: str | None = None,
    *,
    reasoning: str | None = None,
    tool_calls: list[Any] | None = None,
    finish: str | None = None,
    usage: Any = None,
) -> Any:
    delta = SimpleNamespace(
        content=content,
        tool_calls=tool_calls,
        reasoning_content=reasoning,
        model_extra={},
    )
    choices = (
        [SimpleNamespace(delta=delta, finish_reason=finish)]
        if (content or reasoning or tool_calls or finish)
        else []
    )
    return SimpleNamespace(choices=choices, usage=usage)


def tool_part(index: int, *, id: str | None = None, name: str = "", args: str = "") -> Any:
    return SimpleNamespace(index=index, id=id, function=SimpleNamespace(name=name, arguments=args))


class _AsyncList:
    def __init__(self, items: list[Any], error: Exception | None = None) -> None:
        self._items = items
        self._error = error

    def __aiter__(self) -> AsyncIterator[Any]:
        return self._gen()

    async def _gen(self) -> AsyncIterator[Any]:
        for item in self._items:
            yield item
        if self._error is not None:
            raise self._error


class FakeOpenAIClient:
    """Imite `AsyncOpenAI` : `chat.completions.create(**params)` et `models.list()`."""

    def __init__(
        self,
        chunks: list[Any] | None = None,
        *,
        error: Exception | None = None,
        error_after: bool = False,
        models: list[str] | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self._chunks = chunks or []
        self._error = error
        self._after = error_after
        self._models = models or []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.models = SimpleNamespace(list=self._list)

    async def _create(self, **params: Any) -> Any:
        self.calls.append(params)
        if self._error is not None and not self._after:
            raise self._error
        return _AsyncList(self._chunks, self._error if self._after else None)

    async def _list(self) -> Any:
        return SimpleNamespace(data=[SimpleNamespace(id=m) for m in self._models])


class _FakeAnthropicStream:
    def __init__(self, events: list[Any], final: Any, error: Exception | None) -> None:
        self._events = events
        self._final = final
        self._error = error

    async def __aenter__(self) -> _FakeAnthropicStream:
        if self._error is not None:
            raise self._error
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def __aiter__(self) -> AsyncIterator[Any]:
        return _AsyncList(self._events).__aiter__()

    async def get_final_message(self) -> Any:
        return self._final


class FakeAnthropicClient:
    """Imite `AsyncAnthropic` : `beta.messages.stream(**params)` et `models.list()`."""

    def __init__(
        self,
        events: list[Any] | None = None,
        *,
        final: Any = None,
        error: Exception | None = None,
        models: list[str] | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self._events = events or []
        self._final = final
        self._error = error
        self._models = models or []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))
        self.models = SimpleNamespace(list=self._list)

    def _stream(self, **params: Any) -> _FakeAnthropicStream:
        self.calls.append(params)
        return _FakeAnthropicStream(self._events, self._final, self._error)

    async def _list(self) -> Any:
        return _AsyncList([SimpleNamespace(id=m) for m in self._models])


def anthropic_final(
    *,
    text: str = "",
    tool_uses: list[tuple[str, str, dict[str, Any]]] | None = None,
    stop_reason: str = "end_turn",
    input_tokens: int = 10,
    output_tokens: int = 5,
    cache_read: int = 0,
) -> Any:
    content: list[Any] = []
    if text:
        content.append(SimpleNamespace(type="text", text=text))
    for tool_id, name, args in tool_uses or []:
        content.append(SimpleNamespace(type="tool_use", id=tool_id, name=name, input=args))
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=content,
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cache_read,
        ),
    )


def http_response(status: int) -> Any:
    """Réponse minimale acceptée par les constructeurs d'erreurs des SDK."""
    request = SimpleNamespace(method="POST", url="https://exemple.invalid")
    return SimpleNamespace(status_code=status, headers={}, request=request)
