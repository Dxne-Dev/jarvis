"""Outils des automatisations : Jarvis les crée depuis le chat ou la voix, tu valides.

Créer, activer ou désactiver : niveau 2 (une automatisation agira plus tard en ton nom).
Supprimer : niveau 3. Lister : niveau 1.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import Field

from ojarvis.automations.models import (
    Action,
    Instruction,
    Reminder,
    Trigger,
    describe_action,
    describe_trigger,
)
from ojarvis.automations.scheduler import AutomationScheduler
from ojarvis.automations.store import AutomationStore
from ojarvis.core.errors import NotFoundError
from ojarvis.tools.base import Level, Tool, ToolArgs, ToolContext, ToolOutput


class CreateArgs(ToolArgs):
    nom: str = Field(min_length=2, max_length=120, description="Nom court de l'automatisation.")
    declencheur: Trigger = Field(
        description="Quand : horaire (chaque_jour, une_fois, intervalle, chaque_mois) en "
        "heure locale, ou événement du moteur."
    )
    action: Action = Field(
        description="Quoi : rappel (un message tel quel) ou consigne (une tâche que Jarvis "
        "fera avec ses outils de lecture, puis résumera)."
    )


class CreateAutomation(Tool[CreateArgs]):
    name: ClassVar[str] = "creer_automatisation"
    description: ClassVar[str] = (
        "Crée une automatisation (rappel ou tâche récurrente, ex. « tous les matins à 8 h »). "
        "Les heures sont en heure locale ; pour « demain à 9 h », calcule la date à partir de "
        "la date du jour."
    )
    Args: ClassVar[type[ToolArgs]] = CreateArgs
    level: ClassVar[Level] = Level.AGIR

    def __init__(self, store: AutomationStore, scheduler: AutomationScheduler) -> None:
        self._store = store
        self._scheduler = scheduler

    def describe(self, args: CreateArgs) -> str:
        return (
            f"Créer l'automatisation « {args.nom} » : {describe_trigger(args.declencheur)} — "
            f"{describe_action(args.action)}"
        )

    async def run(self, args: CreateArgs, ctx: ToolContext) -> ToolOutput:
        del ctx
        record = await self._store.create(
            args.nom, args.declencheur, args.action, created_by="jarvis"
        )
        await self._scheduler.reload()
        when = (
            f" Prochain passage : {record.next_run_at.isoformat()}." if record.next_run_at else ""
        )
        return ToolOutput(f"Automatisation créée : {record.summary()}.{when}", {"id": record.id})


class NoArgs(ToolArgs):
    pass


class ListAutomations(Tool[NoArgs]):
    name: ClassVar[str] = "lister_automatisations"
    description: ClassVar[str] = "Liste les automatisations, leur horaire et leur état."
    Args: ClassVar[type[ToolArgs]] = NoArgs
    level: ClassVar[Level] = Level.LIRE

    def __init__(self, store: AutomationStore) -> None:
        self._store = store

    def describe(self, args: NoArgs) -> str:
        del args
        return "Lister les automatisations"

    async def run(self, args: NoArgs, ctx: ToolContext) -> ToolOutput:
        del args, ctx
        lines = []
        for record in await self._store.all():
            state = "active" if record.enabled else "désactivée"
            lines.append(f"- [{record.id[:8]}] {record.summary()} ({state})")
        return ToolOutput("\n".join(lines) or "Aucune automatisation.")


class TargetArgs(ToolArgs):
    id: str = Field(
        min_length=4, max_length=32, description="Identifiant (ou son début) de l'automatisation."
    )


async def _find(store: AutomationStore, prefix: str) -> str:
    matching = [a.id for a in await store.all() if a.id.startswith(prefix.strip())]
    if len(matching) != 1:
        raise NotFoundError("Automatisation introuvable (ou identifiant ambigu).")
    return matching[0]


class ToggleArgs(TargetArgs):
    active: bool = Field(description="true pour activer, false pour désactiver.")


class ToggleAutomation(Tool[ToggleArgs]):
    name: ClassVar[str] = "activer_automatisation"
    description: ClassVar[str] = "Active ou désactive une automatisation."
    Args: ClassVar[type[ToolArgs]] = ToggleArgs
    level: ClassVar[Level] = Level.AGIR

    def __init__(self, store: AutomationStore, scheduler: AutomationScheduler) -> None:
        self._store = store
        self._scheduler = scheduler

    def describe(self, args: ToggleArgs) -> str:
        verb = "Activer" if args.active else "Désactiver"
        name = self._store.name_of(args.id)
        return (
            f"{verb} l'automatisation « {name} »"
            if name
            else f"{verb} l'automatisation {args.id[:8]}"
        )

    async def run(self, args: ToggleArgs, ctx: ToolContext) -> ToolOutput:
        del ctx
        record = await self._store.update(await _find(self._store, args.id), enabled=args.active)
        await self._scheduler.reload()
        state = "activée" if record.enabled else "désactivée"
        return ToolOutput(f"Automatisation « {record.name} » {state}.")


class DeleteAutomation(Tool[TargetArgs]):
    name: ClassVar[str] = "supprimer_automatisation"
    description: ClassVar[str] = "Supprime une automatisation."
    Args: ClassVar[type[ToolArgs]] = TargetArgs
    level: ClassVar[Level] = Level.DETRUIRE

    def __init__(self, store: AutomationStore, scheduler: AutomationScheduler) -> None:
        self._store = store
        self._scheduler = scheduler

    def describe(self, args: TargetArgs) -> str:
        name = self._store.name_of(args.id)
        return (
            f"Supprimer l'automatisation « {name} »"
            if name
            else f"Supprimer l'automatisation {args.id[:8]}"
        )

    async def run(self, args: TargetArgs, ctx: ToolContext) -> ToolOutput:
        del ctx
        record = await self._store.delete(await _find(self._store, args.id))
        await self._scheduler.reload()
        return ToolOutput(f"Automatisation « {record.name} » supprimée.")


def automation_tools(
    store: AutomationStore, scheduler: AutomationScheduler
) -> list[Tool[CreateArgs] | Tool[NoArgs] | Tool[ToggleArgs] | Tool[TargetArgs]]:
    return [
        CreateAutomation(store, scheduler),
        ListAutomations(store),
        ToggleAutomation(store, scheduler),
        DeleteAutomation(store, scheduler),
    ]


__all__ = ["Instruction", "Reminder", "automation_tools"]
