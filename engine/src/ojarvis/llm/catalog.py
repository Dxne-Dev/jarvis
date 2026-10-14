"""Catalogue des modèles : capacités et prix (dollars par million de jetons).

Prix relevés le 14/10/2026 dans les docs officielles (DeepSeek, Anthropic). Les modèles
gratuits d'OpenRouter changent souvent : ils sont redécouverts au démarrage.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class Price:
    input: float
    output: float
    cached_input: float = 0.0


@dataclass(frozen=True, slots=True)
class ModelSpec:
    provider: str
    model: str
    label: str
    tools: bool = True
    vision: bool = False
    json_mode: bool = True
    #: La réflexion longue peut être coupée (DeepSeek) ou n'est réglable que par l'effort.
    thinking_toggle: bool = False
    context: int = 128_000
    local: bool = False
    price: Price | None = None

    @property
    def key(self) -> str:
        return f"{self.provider}/{self.model}"


def _deepseek_peak(moment: datetime) -> bool:
    """Heures pleines DeepSeek : 01-04 h et 06-10 h UTC, du lundi au vendredi."""
    utc = moment.astimezone(UTC)
    if utc.weekday() >= 5:
        return False
    return 1 <= utc.hour < 4 or 6 <= utc.hour < 10


STATIC_CATALOG: tuple[ModelSpec, ...] = (
    ModelSpec(
        "deepseek",
        "deepseek-flash",
        "DeepSeek V4.1 Flash",
        thinking_toggle=True,
        context=1_000_000,
        price=Price(input=0.15, output=0.6, cached_input=0.003),
    ),
    ModelSpec(
        "deepseek",
        "deepseek-v4-pro",
        "DeepSeek V4 Pro",
        thinking_toggle=True,
        context=1_000_000,
        price=Price(input=0.66, output=1.98, cached_input=0.022),
    ),
    ModelSpec(
        "anthropic",
        "claude-opus-5-5",
        "Claude Opus 5.5",
        vision=True,
        context=1_000_000,
        price=Price(input=4.0, output=20.0, cached_input=0.2),
    ),
    ModelSpec(
        "anthropic",
        "claude-sonnet-5-5",
        "Claude Sonnet 5.5",
        vision=True,
        context=1_000_000,
        price=Price(input=2.0, output=10.0, cached_input=0.2),
    ),
    ModelSpec(
        "anthropic",
        "claude-haiku-5-5",
        "Claude Haiku 5.5",
        vision=True,
        context=1_000_000,
        price=Price(input=0.1, output=0.5, cached_input=0.01),
    ),
    ModelSpec("openai", "gpt-5", "GPT-5", vision=True, context=400_000),
    ModelSpec("openai", "gpt-5-mini", "GPT-5 mini", vision=True, context=400_000),
    ModelSpec(
        "openrouter",
        "google/gemma-4-26b-a4b-it:free",
        "Gemma 4 26B (gratuit)",
        vision=True,
        context=262_144,
        price=Price(0.0, 0.0),
    ),
    ModelSpec(
        "openrouter",
        "google/gemma-4-31b-it:free",
        "Gemma 4 31B (gratuit)",
        vision=True,
        context=262_144,
        price=Price(0.0, 0.0),
    ),
    ModelSpec(
        "ollama",
        "ministral-3:3b",
        "Ministral 3 3B (local)",
        vision=True,
        context=32_768,
        local=True,
        price=Price(0.0, 0.0),
    ),
)


class Catalog:
    def __init__(self, specs: tuple[ModelSpec, ...] = STATIC_CATALOG) -> None:
        self._specs: dict[str, ModelSpec] = {s.key: s for s in specs}

    def get(self, provider: str, model: str) -> ModelSpec | None:
        return self._specs.get(f"{provider}/{model}")

    def all(self) -> list[ModelSpec]:
        return list(self._specs.values())

    def add(self, spec: ModelSpec) -> None:
        self._specs[spec.key] = spec

    def replace_provider(self, provider: str, specs: list[ModelSpec]) -> None:
        """Remplace les modèles d'un fournisseur (découverte des modèles gratuits)."""
        self._specs = {k: s for k, s in self._specs.items() if s.provider != provider}
        for spec in specs:
            self._specs[spec.key] = spec

    def cost_usd(
        self,
        provider: str,
        model: str,
        *,
        input_tokens: int,
        output_tokens: int,
        cached_input_tokens: int = 0,
        at: datetime | None = None,
    ) -> float | None:
        spec = self.get(provider, model)
        if spec is None or spec.price is None:
            return None
        price = spec.price
        if provider == "deepseek" and _deepseek_peak(at or datetime.now(UTC)):
            price = replace(
                price,
                input=price.input * 2,
                output=price.output * 2,
                cached_input=price.cached_input * 2,
            )
        fresh = max(input_tokens - cached_input_tokens, 0)
        total = (
            fresh * price.input
            + cached_input_tokens * price.cached_input
            + output_tokens * price.output
        )
        return round(total / 1_000_000, 8)


# Préférences parmi les modèles gratuits d'OpenRouter, du plus utile au moins utile.
OPENROUTER_FREE_PREFERENCE = (
    "google/gemma-4-26b-a4b-it:free",
    "google/gemma-4-31b-it:free",
    "thinkingmachines/inkling-small:free",
    "nvidia/nemotron-3.5-lightning:free",
)


def openrouter_free_specs(models: list[dict[str, object]]) -> list[ModelSpec]:
    """Construit les entrées du catalogue depuis la liste publique d'OpenRouter."""
    specs: list[ModelSpec] = []
    for item in models:
        model_id = str(item.get("id", ""))
        if not model_id.endswith(":free"):
            continue
        architecture = item.get("architecture")
        modalities = (
            architecture.get("input_modalities", []) if isinstance(architecture, dict) else []
        )
        params = item.get("supported_parameters", [])
        params = params if isinstance(params, list) else []
        context = item.get("context_length", 0)
        specs.append(
            ModelSpec(
                "openrouter",
                model_id,
                f"{item.get('name', model_id)}",
                tools="tools" in params,
                vision=isinstance(modalities, list) and "image" in modalities,
                json_mode="response_format" in params,
                context=context if isinstance(context, int) else 0,
                price=Price(0.0, 0.0),
            )
        )
    rank = {name: i for i, name in enumerate(OPENROUTER_FREE_PREFERENCE)}
    specs.sort(key=lambda s: (rank.get(s.model, len(rank)), -s.context))
    return specs
