"""Lecture tolérante du JSON produit par un modèle.

Leçon de l'ancien Jarvis : un petit modèle a renvoyé `{"steps": [...]}]`. On retire les
balises de code et le texte autour, on lit la première valeur JSON complète et on ignore
le surplus.
"""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)
_TRAILING_COMMA = re.compile(r",\s*([}\]])")


class JSONExtractionError(ValueError):
    pass


def extract_json(text: str) -> Any:
    """Renvoie la première valeur JSON (objet ou tableau) trouvée dans `text`."""
    candidates: list[str] = []
    fenced = _FENCE.search(text)
    if fenced:
        candidates.append(fenced.group(1))
    candidates.append(text)
    decoder = json.JSONDecoder()
    last_error: Exception | None = None
    for candidate in candidates:
        for start_char in ("{", "["):
            start = candidate.find(start_char)
            while start != -1:
                for attempt in (candidate[start:], _TRAILING_COMMA.sub(r"\1", candidate[start:])):
                    try:
                        value, _ = decoder.raw_decode(attempt)
                    except json.JSONDecodeError as exc:
                        last_error = exc
                        continue
                    return value
                start = candidate.find(start_char, start + 1)
    raise JSONExtractionError(f"aucun JSON lisible ({last_error})")


def loads_arguments(raw: str) -> dict[str, Any]:
    """Arguments d'un appel d'outil : objet JSON, ou objet vide si la chaîne est vide."""
    if not raw.strip():
        return {}
    value = extract_json(raw)
    if not isinstance(value, dict):
        raise JSONExtractionError("les arguments doivent être un objet JSON")
    return value
