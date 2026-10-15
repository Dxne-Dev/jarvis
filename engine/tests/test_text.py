"""Conversion du markdown en texte brut (aperçus, voix)."""

from __future__ import annotations

import pytest

from ojarvis.core.text import plain_text


@pytest.mark.parametrize(
    ("markdown", "expected"),
    [
        ("Bien reçu : **Et maintenant ?**. Fin.", "Bien reçu : Et maintenant ?. Fin."),
        ("# Titre\n\n- un\n- deux\n* trois", "Titre un deux trois"),
        ("1. premier\n2) second", "premier second"),
        ("Voir [la doc](https://exemple.fr) et ![logo](a.png)", "Voir la doc et logo"),
        ("`snake_case_var` reste intact", "snake_case_var reste intact"),
        ("```python\nprint(1)\n```", "print(1)"),
        ("*italique*, _aussi_ et ~~barré~~", "italique, aussi et barré"),
        ("2 * 3 * 4 = 24", "2 * 3 * 4 = 24"),
        ("> une citation", "une citation"),
        ("", ""),
    ],
)
def test_plain_text(markdown: str, expected: str) -> None:
    assert plain_text(markdown) == expected
