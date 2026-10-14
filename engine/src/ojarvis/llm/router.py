"""Routeur de modèles : choisit un fournisseur selon la tâche, et bascule si l'un tombe.

- Chaque type de tâche a une liste ordonnée de routes (fournisseur, modèle, réflexion).
- Les données sensibles et le mode hors ligne ne passent que par un modèle local.
- Réglages : l'utilisateur peut imposer un modèle par type de tâche.
- Un fournisseur qui échoue est mis de côté un temps (disjoncteur) ; l'interface est
  prévenue par un événement, et la requête bascule sur la route suivante tant
  qu'aucun texte n'a été envoyé.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass, field

from ojarvis.core.logs import get_logger
from ojarvis.events.bus import EventBus
from ojarvis.llm.catalog import Catalog, ModelSpec
from ojarvis.llm.errors import (
    AuthenticationFailedError,
    ContentRefusedError,
    LLMError,
    NoRouteAvailableError,
    NotConfiguredError,
    QuotaExhaustedError,
)
from ojarvis.llm.providers.base import Provider
from ojarvis.llm.types import (
    LLMRequest,
    LLMResult,
    ReasoningDelta,
    RouteInfo,
    StreamEnd,
    StreamEvent,
    TaskType,
    TextDelta,
    ToolCall,
    ToolCallReady,
    Usage,
)
from ojarvis.tracing.tracer import Tracer

log = get_logger(__name__)


#: « N'importe quel modèle de ce fournisseur qui convient », dans l'ordre du catalogue
#: (utile pour les modèles gratuits d'OpenRouter, qui changent souvent).
ANY_MODEL = "*"


@dataclass(frozen=True, slots=True)
class Route:
    provider: str
    model: str
    thinking: bool = False

    @property
    def key(self) -> str:
        return f"{self.provider}/{self.model}"


#: Politique par défaut. Rapide et bon marché pour la voix et le chat courant.
DEFAULT_POLICY: Mapping[TaskType, tuple[Route, ...]] = {
    "voice": (
        Route("deepseek", "deepseek-flash"),
        Route("anthropic", "claude-opus-5-5"),
        Route("openai", "gpt-5-mini"),
        Route("openrouter", ANY_MODEL),
        Route("ollama", "ministral-3:3b"),
    ),
    "chat": (
        Route("deepseek", "deepseek-flash"),
        Route("anthropic", "claude-opus-5-5"),
        Route("openai", "gpt-5"),
        Route("openrouter", ANY_MODEL),
        Route("ollama", "ministral-3:3b"),
    ),
    "reasoning": (
        Route("deepseek", "deepseek-v4-pro", thinking=True),
        Route("anthropic", "claude-opus-5-5", thinking=True),
        Route("openai", "gpt-5", thinking=True),
        Route("deepseek", "deepseek-flash", thinking=True),
        Route("openrouter", ANY_MODEL),
        Route("ollama", "ministral-3:3b"),
    ),
    "extract": (
        Route("deepseek", "deepseek-flash"),
        Route("anthropic", "claude-haiku-5-5"),
        Route("openai", "gpt-5-mini"),
        Route("openrouter", ANY_MODEL),
        Route("ollama", "ministral-3:3b"),
    ),
    "title": (
        Route("deepseek", "deepseek-flash"),
        Route("anthropic", "claude-haiku-5-5"),
        Route("openai", "gpt-5-mini"),
        Route("openrouter", ANY_MODEL),
        Route("ollama", "ministral-3:3b"),
    ),
    "vision": (
        Route("openrouter", ANY_MODEL),
        Route("anthropic", "claude-opus-5-5"),
        Route("openai", "gpt-5"),
        Route("ollama", "ministral-3:3b"),
    ),
}


@dataclass
class ProviderHealth:
    failures: int = 0
    open_until: float = 0.0
    last_error: str | None = None
    degraded: bool = False

    def available(self, now: float) -> bool:
        return now >= self.open_until


@dataclass
class Constraints:
    needs_tools: bool = False
    needs_vision: bool = False
    sensitive: bool = False
    offline: bool = False


@dataclass
class RoutedStream:
    """Ce que le routeur sait de l'essai en cours (lu par l'appelant à la fin)."""

    route: Route | None = None
    attempts: list[str] = field(default_factory=list)


Overrides = Callable[[], Mapping[str, str]]


class ModelRouter:
    def __init__(
        self,
        providers: Mapping[str, Provider],
        catalog: Catalog,
        *,
        bus: EventBus | None = None,
        tracer: Tracer | None = None,
        overrides: Overrides | None = None,
        policy: Mapping[TaskType, tuple[Route, ...]] = DEFAULT_POLICY,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.providers = dict(providers)
        self.catalog = catalog
        self.policy = policy
        self._bus = bus
        self._tracer = tracer
        self._overrides = overrides or dict
        self._clock = clock
        self.health: dict[str, ProviderHealth] = {name: ProviderHealth() for name in providers}

    # ---------------------------------------------------------------- choix des routes

    def _spec(self, route: Route) -> ModelSpec | None:
        return self.catalog.get(route.provider, route.model)

    def _fits(self, route: Route, constraints: Constraints) -> bool:
        provider = self.providers.get(route.provider)
        if provider is None or not provider.is_configured():
            return False
        spec = self._spec(route)
        if (constraints.sensitive or constraints.offline) and not provider.local:
            return False
        if spec is None:
            return not (constraints.needs_tools or constraints.needs_vision)
        if constraints.needs_tools and not spec.tools:
            return False
        return not (constraints.needs_vision and not spec.vision)

    def routes(self, task: TaskType, constraints: Constraints | None = None) -> list[Route]:
        """Routes candidates, dans l'ordre, déjà filtrées (clé, capacités, sensibilité)."""
        constraints = constraints or Constraints()
        candidates: list[Route] = []
        override = self._overrides().get(task)
        if override and "/" in override:
            provider, model = override.split("/", 1)
            default_thinking = any(r.thinking for r in self.policy.get(task, ()))
            candidates.append(Route(provider, model, thinking=default_thinking))
        candidates.extend(self.policy.get(task, ()))
        if constraints.sensitive or constraints.offline:
            candidates.extend(
                Route(spec.provider, spec.model) for spec in self.catalog.all() if spec.local
            )
        seen: set[str] = set()
        result: list[Route] = []
        for candidate in candidates:
            route = self._resolve(candidate, constraints)
            if route is None or route.key in seen or not self._fits(route, constraints):
                continue
            seen.add(route.key)
            result.append(route)
        return result

    def _resolve(self, route: Route, constraints: Constraints) -> Route | None:
        if route.model != ANY_MODEL:
            return route
        for spec in self.catalog.all():
            if spec.provider != route.provider:
                continue
            concrete = Route(spec.provider, spec.model, route.thinking)
            if self._fits(concrete, constraints):
                return concrete
        return None

    # ---------------------------------------------------------------- santé des fournisseurs

    async def _record_failure(self, route: Route, error: LLMError) -> None:
        health = self.health.setdefault(route.provider, ProviderHealth())
        health.failures += 1
        health.last_error = type(error).__name__
        now = self._clock()
        if isinstance(error, AuthenticationFailedError | QuotaExhaustedError | NotConfiguredError):
            cooldown = 600.0
        elif health.failures >= 2:
            cooldown = min(30.0 * 2 ** (health.failures - 2), 300.0)
        else:
            cooldown = 0.0
        health.open_until = now + cooldown
        if cooldown and not health.degraded:
            health.degraded = True
            await self._publish(
                "llm.provider_degraded",
                {
                    "provider": route.provider,
                    "reason": error.public,
                    "error": type(error).__name__,
                    "retry_in_s": round(cooldown),
                },
            )

    async def _record_success(self, route: Route) -> None:
        health = self.health.setdefault(route.provider, ProviderHealth())
        recovered = health.degraded
        health.failures = 0
        health.open_until = 0.0
        health.degraded = False
        if recovered:
            await self._publish("llm.provider_recovered", {"provider": route.provider})

    async def _publish(self, event_type: str, payload: dict[str, object]) -> None:
        if self._bus is not None:
            await self._bus.publish(event_type, payload, source="llm")

    def status(self) -> list[dict[str, object]]:
        now = self._clock()
        return [
            {
                "provider": name,
                "configured": provider.is_configured(),
                "local": provider.local,
                "available": self.health[name].available(now),
                "degraded": self.health[name].degraded,
                "last_error": self.health[name].last_error,
            }
            for name, provider in self.providers.items()
        ]

    # ---------------------------------------------------------------- appel en flux

    async def stream(
        self,
        task: TaskType,
        request: LLMRequest,
        constraints: Constraints | None = None,
        *,
        state: RoutedStream | None = None,
    ) -> AsyncIterator[StreamEvent | RouteInfo]:
        """Flux d'événements, précédé d'un `RouteInfo`.

        Bascule sur la route suivante si l'échec survient avant le premier morceau ;
        après, l'erreur remonte (le texte déjà envoyé ne peut pas être repris).
        """
        constraints = constraints or Constraints(
            needs_tools=bool(request.tools),
            needs_vision=any(m.images for m in request.messages),
        )
        state = state or RoutedStream()
        routes = self.routes(task, constraints)
        if not routes:
            raise NoRouteAvailableError(f"aucune route pour {task}")
        now = self._clock()
        healthy = [
            r for r in routes if self.health.setdefault(r.provider, ProviderHealth()).available(now)
        ]
        ordered = healthy or routes  # tous en panne : on retente quand même dans l'ordre
        last_error: LLMError | None = None
        previous: Route | None = None
        for route in ordered:
            state.route = route
            state.attempts.append(route.key)
            routed = LLMRequest(
                messages=request.messages,
                tools=request.tools,
                json_mode=request.json_mode,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
                thinking=request.thinking or route.thinking,
            )
            provider = self.providers[route.provider]
            started = False
            try:
                async for event in provider.stream(routed, route.model):
                    if not started:
                        started = True
                        yield RouteInfo(
                            route.provider,
                            route.model,
                            fallback_from=previous.key if previous else None,
                        )
                    yield event
            except ContentRefusedError:
                raise
            except LLMError as error:
                await self._record_failure(route, error)
                log.warning(
                    "llm_route_failed",
                    provider=route.provider,
                    model=route.model,
                    error=type(error).__name__,
                    after_output=started,
                )
                if started:
                    raise
                last_error = error
                if previous is None or previous.provider != route.provider:
                    await self._publish(
                        "llm.fallback",
                        {"task": task, "from": route.key, "reason": error.public},
                    )
                previous = route
                continue
            await self._record_success(route)
            return
        raise last_error or NoRouteAvailableError(f"aucune route n'a répondu pour {task}")

    async def stream_traced(
        self,
        task: TaskType,
        request: LLMRequest,
        constraints: Constraints | None = None,
        *,
        state: RoutedStream | None = None,
    ) -> AsyncIterator[StreamEvent | RouteInfo]:
        """Comme `stream`, dans une étape de trace « appel LLM » (jetons, coût, latence)."""
        state = state or RoutedStream()
        start = time.perf_counter()
        first_token: float | None = None
        usage = Usage()
        finish: str | None = None

        async def events() -> AsyncIterator[StreamEvent | RouteInfo]:
            nonlocal first_token, usage, finish
            async for event in self.stream(task, request, constraints, state=state):
                if isinstance(event, TextDelta | ToolCallReady) and first_token is None:
                    first_token = time.perf_counter()
                elif isinstance(event, StreamEnd):
                    usage = event.usage
                    finish = event.finish_reason
                yield event

        if self._tracer is None:
            async for event in events():
                yield event
            return

        async with self._tracer.span("appel LLM", kind="llm", task=task) as span:
            try:
                async for event in events():
                    yield event
            finally:
                route = state.route
                span.set(
                    provider=route.provider if route else None,
                    model=route.model if route else None,
                    thinking=(request.thinking or route.thinking) if route else None,
                    attempts=list(state.attempts),
                    tokens_in=usage.input_tokens,
                    tokens_out=usage.output_tokens,
                    tokens_cached=usage.cached_input_tokens,
                    cost_usd=self.cost(route, usage),
                    ttft_ms=round((first_token - start) * 1000, 1) if first_token else None,
                    finish_reason=finish,
                )

    def cost(self, route: Route | None, usage: Usage) -> float | None:
        if route is None:
            return None
        return self.catalog.cost_usd(
            route.provider,
            route.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cached_input_tokens=usage.cached_input_tokens,
        )

    async def complete(
        self,
        task: TaskType,
        request: LLMRequest,
        constraints: Constraints | None = None,
        *,
        on_text: Callable[[str], None] | None = None,
    ) -> LLMResult:
        """Appel complet, tracé (modèle, jetons, coût, latence, temps du premier jeton)."""
        start = time.perf_counter()
        first_token: float | None = None
        text: list[str] = []
        reasoning: list[str] = []
        calls: list[ToolCall] = []
        usage = Usage()
        finish: str | None = None
        info: RouteInfo | None = None
        blocks: tuple[object, ...] = ()
        state = RoutedStream()
        async for event in self.stream_traced(task, request, constraints, state=state):
            if isinstance(event, RouteInfo):
                info = event
            elif isinstance(event, TextDelta):
                if first_token is None:
                    first_token = time.perf_counter()
                text.append(event.text)
                if on_text is not None:
                    on_text(event.text)
            elif isinstance(event, ReasoningDelta):
                reasoning.append(event.text)
            elif isinstance(event, ToolCallReady):
                if first_token is None:
                    first_token = time.perf_counter()
                calls.append(event.call)
            elif isinstance(event, StreamEnd):
                usage = event.usage
                finish = event.finish_reason
                blocks = event.provider_blocks
        if info is None:
            raise NoRouteAvailableError("aucune réponse")
        return LLMResult(
            text="".join(text),
            reasoning="".join(reasoning),
            tool_calls=calls,
            usage=usage,
            finish_reason=finish,
            provider=info.provider,
            model=info.model,
            cost_usd=self.cost(state.route, usage) or 0.0,
            latency_ms=round((time.perf_counter() - start) * 1000, 1),
            ttft_ms=round((first_token - start) * 1000, 1) if first_token else None,
            provider_blocks=blocks,
        )
