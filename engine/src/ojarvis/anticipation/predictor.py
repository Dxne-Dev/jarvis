"""Anticipation : des suggestions tirées de tes habitudes, avec un score de confiance.

Ce module lit la mémoire et ne la modifie jamais : il ne reçoit qu'une vue en lecture du
graphe (`GraphView`). Règle de départ : un projet ou un sujet dont tu parlais souvent et dont
tu ne parles plus depuis quelques jours (« tu n'as pas touché à X depuis 5 jours »).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from ojarvis.anticipation.store import Option, Suggestion, SuggestionStore
from ojarvis.core.clock import utc_now
from ojarvis.memory.graph import EntityRecord, RelationRecord

IDLE_DAYS = 5
MIN_MENTIONS = 3


class GraphView(Protocol):
    """La seule chose que l'anticipation peut faire avec la mémoire : la lire."""

    async def graph(
        self, *, limit: int = 300
    ) -> tuple[list[EntityRecord], list[RelationRecord]]: ...


def confidence(mentions: int, idle_days: int) -> float:
    """Plus tu en parlais, plus l'absence se remarque ; un peu plus avec le temps."""
    return round(min(0.4 + 0.07 * min(mentions, 6) + 0.01 * min(idle_days, 20), 0.9), 2)


class Predictor:
    def __init__(
        self,
        graph: GraphView,
        suggestions: SuggestionStore,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._graph = graph
        self._suggestions = suggestions
        self._clock = clock

    async def run(self) -> list[Suggestion]:
        entities, _ = await self._graph.graph(limit=300)
        now = self._clock()
        made: list[Suggestion] = []
        for entity in entities:
            if entity.kind not in ("projet", "sujet") or entity.mentions < MIN_MENTIONS:
                continue
            idle = (now - entity.last_seen_at).days
            if idle < IDLE_DAYS:
                continue
            verb = "touché à" if entity.kind == "projet" else "parlé de"
            suggestion = await self._suggestions.propose(
                kind="inactivite",
                title=f"Tu n'as pas {verb} {entity.name} depuis {idle} jours.",
                detail=entity.description,
                options=[
                    Option(
                        "reprendre",
                        "Reprendre",
                        f"Résume-moi où j'en étais avec {entity.name} et propose-moi la "
                        "prochaine étape.",
                    )
                ],
                confidence=confidence(entity.mentions, idle),
                # Une nouvelle absence (après en avoir reparlé) peut redonner une suggestion.
                fingerprint=f"inactivite:{entity.id}:{entity.last_seen_at.date().isoformat()}",
            )
            if suggestion is not None:
                made.append(suggestion)
        return made
