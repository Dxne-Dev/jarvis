"""Le planificateur : il réveille les automatisations à l'heure dite ou sur un événement.

- À l'heure : il dort jusqu'à la prochaine échéance (30 s au plus) ; au réveil, chaque
  automatisation due part dans le moteur de workflows. Machine éteinte à l'heure dite :
  au redémarrage, une échéance manquée de moins de 6 h est rattrapée, au-delà elle est
  notée « manquée » et l'on passe à la suivante.
- Sur un événement : chaque événement du bus est comparé aux automatisations qui
  l'attendent. Ce que font les automatisations elles-mêmes ne déclenche rien (pas de
  boucle), et une même automatisation ne part pas plus d'une fois par minute.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from ojarvis.automations.models import EventTrigger, Reminder, TimeTrigger
from ojarvis.automations.store import AutomationRecord, AutomationStore
from ojarvis.core.clock import utc_now
from ojarvis.core.logs import get_logger
from ojarvis.events.bus import Event, EventBus, Subscription
from ojarvis.workflows.engine import RunRecord, WorkflowEngine

log = get_logger(__name__)

CATCH_UP = timedelta(hours=6)
MIN_EVENT_GAP = timedelta(minutes=1)
MAX_SLEEP_S = 30.0
#: Les exécutions de workflows portent cet identifiant de corrélation : leurs événements
#: ne déclenchent pas d'automatisation.
WORKFLOW_CORRELATION_PREFIX = "wf"


def steps_for(automation: AutomationRecord) -> list[dict[str, Any]]:
    action = automation.action
    if isinstance(action, Reminder):
        return [{"type": "notifier", "titre": automation.name, "texte": action.texte}]
    return [
        {"type": "consigne", "texte": action.texte},
        {"type": "notifier", "titre": automation.name},
    ]


def matches(trigger: EventTrigger, event: Event) -> bool:
    if event.type != trigger.evenement:
        return False
    return all(event.payload.get(key) == value for key, value in trigger.filtre.items())


class AutomationScheduler:
    def __init__(
        self,
        *,
        store: AutomationStore,
        workflows: WorkflowEngine,
        bus: EventBus,
        clock: Callable[[], datetime] = utc_now,
        catch_up: timedelta = CATCH_UP,
    ) -> None:
        self._store = store
        self._workflows = workflows
        self._bus = bus
        self._clock = clock
        self._catch_up = catch_up
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._subscription: Subscription | None = None
        self._on_events: list[AutomationRecord] = []
        self._last_event_fire: dict[str, datetime] = {}

    async def start(self) -> None:
        await self.reload()
        self._subscription = self._bus.subscribe("*", self._on_event)
        self._task = asyncio.create_task(self._loop())

    async def close(self) -> None:
        if self._subscription is not None:
            self._subscription.close()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task

    async def reload(self) -> None:
        """Les automatisations ont changé : relire celles qui attendent un événement."""
        self._on_events = [
            a for a in await self._store.all() if a.enabled and isinstance(a.trigger, EventTrigger)
        ]
        self._wake.set()

    # ------------------------------------------------------------------ à l'heure

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                log.exception("scheduler_tick_failed")
            following = await self._store.next_due()
            delay = MAX_SLEEP_S
            if following is not None:
                delay = max(0.5, min(MAX_SLEEP_S, (following - self._clock()).total_seconds()))
            self._wake.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), delay)

    async def tick(self) -> list[str]:
        """Lance ce qui est dû ; rend les identifiants des automatisations lancées."""
        now = self._clock()
        fired: list[str] = []
        for automation in await self._store.due(now):
            if automation.next_run_at is None:
                continue
            late = now - automation.next_run_at
            if late > self._catch_up:
                await self._store.mark(automation.id, at=now, status="missed", ran=False)
                await self._bus.publish(
                    "automation.missed",
                    {
                        "id": automation.id,
                        "name": automation.name,
                        "due": automation.next_run_at.isoformat(),
                    },
                )
                continue
            await self.fire(automation, reason="horaire", now=now)
            fired.append(automation.id)
        return fired

    # ------------------------------------------------------------------ sur un événement

    async def _on_event(self, event: Event) -> None:
        if event.type == "workflow.finished" and event.payload.get("automation"):
            status = "ok" if event.payload.get("status") == "done" else "failed"
            await self._store.set_status(str(event.payload["automation"]), status)
            return
        if (event.correlation_id or "").startswith(WORKFLOW_CORRELATION_PREFIX):
            return  # produit par une automatisation : pas de réaction en chaîne
        for automation in list(self._on_events):
            trigger = automation.trigger
            if not isinstance(trigger, EventTrigger) or not matches(trigger, event):
                continue
            now = self._clock()
            last = self._last_event_fire.get(automation.id)
            if last is not None and now - last < MIN_EVENT_GAP:
                continue
            self._last_event_fire[automation.id] = now
            payload = json.loads(json.dumps(event.payload, default=str))
            await self.fire(
                automation, reason="evenement", now=now, event={"type": event.type, **payload}
            )

    # ------------------------------------------------------------------ lancement

    async def fire(
        self,
        automation: AutomationRecord,
        *,
        reason: str,
        now: datetime | None = None,
        event: dict[str, Any] | None = None,
    ) -> RunRecord:
        now = now or self._clock()
        context: dict[str, Any] = {"raison": reason}
        if event is not None:
            context["evenement"] = event
        run = await self._workflows.submit(
            kind="automation",
            title=automation.name,
            steps=steps_for(automation),
            context=context,
            automation_id=automation.id,
        )
        updated = await self._store.mark(
            automation.id, at=now, status="running", ran=True, reschedule=reason != "manuel"
        )
        await self._bus.publish(
            "automation.fired",
            {"id": automation.id, "name": automation.name, "run": run.id, "reason": reason},
        )
        if not updated.enabled or isinstance(automation.trigger, EventTrigger):
            await self.reload()
        log.info("automation_fired", automation=automation.id, reason=reason)
        return run


__all__ = ["AutomationScheduler", "TimeTrigger", "matches", "steps_for"]
