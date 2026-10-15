"""Ce qu'est une automatisation : un déclencheur, une action, rien de plus.

- Déclencheur : une heure (chaque jour, une fois, à intervalle, chaque mois) ou un
  événement du moteur (un plan se termine, un message Telegram arrive…).
- Action : un rappel (un message, tel quel) ou une consigne (Jarvis fait la tâche avec ses
  outils de lecture, puis te résume ce qu'il a fait). Une action de niveau 2 ou 3 n'est
  jamais faite seule : Jarvis prépare un plan et te prévient.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from ojarvis.automations.schedule import Daily, Every, Monthly, Once, Schedule, describe

#: Événements qui peuvent déclencher une automatisation (les autres sont trop bavards).
EVENTS: dict[str, str] = {
    "engine.started": "Au démarrage de Jarvis",
    "plan.finished": "Quand un plan se termine",
    "plan.proposed": "Quand un plan attend ta validation",
    "memory.added": "Quand Jarvis retient quelque chose de nouveau",
    "telegram.message": "Quand un message Telegram arrive",
    "voice.turn": "Quand tu parles à Jarvis",
}


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TimeTrigger(_Base):
    type: Literal["horaire"] = "horaire"
    quand: Schedule


class EventTrigger(_Base):
    type: Literal["evenement"] = "evenement"
    evenement: Literal[
        "engine.started",
        "plan.finished",
        "plan.proposed",
        "memory.added",
        "telegram.message",
        "voice.turn",
    ]
    #: Conditions sur le contenu de l'événement (ex. {"status": "failed"}).
    filtre: dict[str, str | int | bool] = Field(default_factory=dict)


Trigger = Annotated[TimeTrigger | EventTrigger, Field(discriminator="type")]


class Reminder(_Base):
    type: Literal["rappel"] = "rappel"
    texte: str = Field(min_length=1, max_length=1000, description="Le message à te rappeler.")


class Instruction(_Base):
    type: Literal["consigne"] = "consigne"
    texte: str = Field(
        min_length=3,
        max_length=2000,
        description="Ce que Jarvis doit faire (avec ses outils de lecture), puis te résumer.",
    )


Action = Annotated[Reminder | Instruction, Field(discriminator="type")]


class AutomationIn(_Base):
    nom: str = Field(min_length=2, max_length=120)
    declencheur: Trigger
    action: Action


def describe_trigger(trigger: TimeTrigger | EventTrigger) -> str:
    if isinstance(trigger, TimeTrigger):
        return describe(trigger.quand)
    label = EVENTS[trigger.evenement]
    if trigger.filtre:
        conditions = ", ".join(f"{k} = {v}" for k, v in trigger.filtre.items())
        return f"{label} ({conditions})"
    return label


def describe_action(action: Reminder | Instruction) -> str:
    text = action.texte if len(action.texte) <= 90 else action.texte[:87] + "…"
    return f"Rappel : « {text} »" if isinstance(action, Reminder) else f"Consigne : « {text} »"


def is_one_shot(trigger: TimeTrigger | EventTrigger) -> bool:
    """Une automatisation ponctuelle se désactive après son passage."""
    return isinstance(trigger, TimeTrigger) and isinstance(trigger.quand, Once)


__all__ = [
    "EVENTS",
    "Action",
    "AutomationIn",
    "Daily",
    "EventTrigger",
    "Every",
    "Instruction",
    "Monthly",
    "Once",
    "Reminder",
    "TimeTrigger",
    "Trigger",
    "describe_action",
    "describe_trigger",
    "is_one_shot",
]
