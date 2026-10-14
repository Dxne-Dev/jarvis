"""Sorties structurées robustes.

Ordre : appel d'outil natif (un outil `repondre` dont les paramètres sont le schéma),
sinon mode JSON ; lecture tolérante ; validation Pydantic ; un seul nouvel essai avec
l'erreur expliquée au modèle ; puis échec propre.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ValidationError

from ojarvis.llm.errors import StructuredOutputError
from ojarvis.llm.jsonparse import JSONExtractionError, extract_json
from ojarvis.llm.router import Constraints, ModelRouter
from ojarvis.llm.types import LLMRequest, Message, TaskType, ToolSpec

TOOL_NAME = "repondre"


def _schema(model: type[BaseModel]) -> dict[str, Any]:
    schema = model.model_json_schema()
    schema.pop("title", None)
    return schema


async def generate_structured[T: BaseModel](
    router: ModelRouter,
    task: TaskType,
    messages: list[Message],
    schema: type[T],
    *,
    constraints: Constraints | None = None,
    max_tokens: int = 2000,
) -> T:
    tool = ToolSpec(
        name=TOOL_NAME,
        description="Donne ta réponse finale, au format exact attendu.",
        parameters=_schema(schema),
    )
    instruction = Message(
        role="system",
        content=(
            f"Appelle l'outil `{TOOL_NAME}` avec ta réponse. Si tu ne peux pas appeler "
            "d'outil, réponds uniquement par un objet JSON conforme à ce schéma : "
            + json.dumps(_schema(schema), ensure_ascii=False)
        ),
    )
    conversation = [*messages, instruction]
    last_error = ""
    for attempt in range(2):
        request = LLMRequest(
            messages=conversation, tools=[tool], json_mode=False, max_tokens=max_tokens
        )
        result = await router.complete(task, request, constraints)
        raw: Any
        try:
            call = next((c for c in result.tool_calls if c.name == TOOL_NAME), None)
            raw = call.arguments if call is not None else extract_json(result.text)
            return schema.model_validate(raw)
        except (JSONExtractionError, ValidationError) as exc:
            last_error = str(exc)[:800]
        if attempt == 0:
            conversation = [
                *conversation,
                Message(role="assistant", content=result.text or "(appel d'outil invalide)"),
                Message(
                    role="user",
                    content=(
                        "Ta réponse n'est pas exploitable : "
                        f"{last_error}\nRecommence en respectant exactement le schéma."
                    ),
                ),
            ]
    raise StructuredOutputError(f"réponse invalide après un nouvel essai : {last_error}")
