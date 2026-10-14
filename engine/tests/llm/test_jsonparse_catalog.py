from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ojarvis.llm.catalog import Catalog, ModelSpec, Price, openrouter_free_specs
from ojarvis.llm.jsonparse import JSONExtractionError, extract_json, loads_arguments


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"a": 1}', {"a": 1}),
        ('{"steps": [1, 2]}]', {"steps": [1, 2]}),  # le cas réel de l'ancien Jarvis
        ('Voici :\n```json\n{"ok": true}\n```\nVoilà.', {"ok": True}),
        ('Réponse : {"a": [1, 2,], "b": 3,}', {"a": [1, 2], "b": 3}),
        ("[1, 2, 3] et la suite", [1, 2, 3]),
        ('texte {pas json} puis {"vrai": 1}', {"vrai": 1}),
    ],
)
def test_extract_json_tolerates_noise(text: str, expected: object) -> None:
    assert extract_json(text) == expected


@pytest.mark.parametrize("text", ["", "aucun json ici", "{cassé"])
def test_extract_json_fails_cleanly(text: str) -> None:
    with pytest.raises(JSONExtractionError):
        extract_json(text)


def test_loads_arguments() -> None:
    assert loads_arguments("") == {}
    assert loads_arguments('{"q": "météo"}') == {"q": "météo"}
    with pytest.raises(JSONExtractionError):
        loads_arguments("[1, 2]")


def test_cost_uses_cached_tokens_and_deepseek_peak_hours() -> None:
    catalog = Catalog()
    off_peak = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)  # mercredi, heures creuses
    peak = datetime(2026, 10, 14, 7, 0, tzinfo=UTC)  # mercredi 7 h UTC, heures pleines
    weekend = datetime(2026, 10, 17, 7, 0, tzinfo=UTC)  # samedi

    def flash(at: datetime) -> float | None:
        return catalog.cost_usd(
            "deepseek", "deepseek-flash", input_tokens=1_000_000, output_tokens=1_000_000, at=at
        )

    assert flash(off_peak) == pytest.approx(0.75)
    assert flash(peak) == pytest.approx(1.5)
    assert flash(weekend) == pytest.approx(0.75)
    cached = catalog.cost_usd(
        "deepseek",
        "deepseek-flash",
        input_tokens=1_000_000,
        output_tokens=0,
        cached_input_tokens=1_000_000,
        at=off_peak,
    )
    assert cached == pytest.approx(0.003)
    assert catalog.cost_usd("ollama", "ministral-3:3b", input_tokens=10, output_tokens=10) == 0.0
    # Prix inconnu : rien n'est inventé.
    assert catalog.cost_usd("openai", "gpt-5", input_tokens=10, output_tokens=10) is None
    assert catalog.cost_usd("inconnu", "x", input_tokens=10, output_tokens=10) is None


def test_catalog_replace_provider() -> None:
    catalog = Catalog()
    catalog.replace_provider(
        "openrouter", [ModelSpec("openrouter", "m:free", "M", price=Price(0, 0))]
    )
    assert [s.model for s in catalog.all() if s.provider == "openrouter"] == ["m:free"]
    assert catalog.get("deepseek", "deepseek-flash") is not None


def test_openrouter_free_specs_parsing_and_ranking() -> None:
    models = [
        {"id": "payant/modele", "context_length": 9},
        {
            "id": "autre/petit:free",
            "name": "Petit",
            "context_length": 1000,
            "architecture": {"input_modalities": ["text"]},
            "supported_parameters": ["tools"],
        },
        {
            "id": "google/gemma-4-31b-it:free",
            "name": "Gemma",
            "context_length": 262144,
            "architecture": {"input_modalities": ["text", "image"]},
            "supported_parameters": ["tools", "response_format"],
        },
    ]
    specs = openrouter_free_specs(models)
    assert [s.model for s in specs] == ["google/gemma-4-31b-it:free", "autre/petit:free"]
    gemma = specs[0]
    assert gemma.vision
    assert gemma.tools
    assert gemma.json_mode
    assert not specs[1].vision
    assert gemma.price == Price(0.0, 0.0)
