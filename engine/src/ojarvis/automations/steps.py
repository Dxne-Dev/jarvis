"""Les étapes qu'exécute une automatisation dans le moteur de workflows.

- `consigne` : Jarvis fait la tâche dans la conversation de l'automatisation, avec ses
  outils de lecture ; une action (niveau 2 ou 3) devient un plan qui attend ta décision.
  Ce qui a déclenché l'automatisation (un événement) lui arrive comme une donnée.
- `notifier` : te prévient (app, bureau, Telegram) avec le rappel ou le résultat.
"""

from __future__ import annotations

import json
from typing import Any

from ojarvis.automations.store import AutomationStore
from ojarvis.chat.service import ChatService
from ojarvis.core.errors import UpstreamError
from ojarvis.notifications import Notice, Notifier
from ojarvis.tools.guards import as_data
from ojarvis.workflows.engine import RunRecord, StepHandler


class AutomationSteps:
    def __init__(self, *, store: AutomationStore, chat: ChatService, notifier: Notifier) -> None:
        self._store = store
        self._chat = chat
        self._notifier = notifier

    def handlers(self) -> dict[str, StepHandler]:
        return {"consigne": self.instruction, "notifier": self.notify}

    async def instruction(self, step: dict[str, Any], run: RunRecord) -> dict[str, Any]:
        automation = await self._store.get(run.automation_id) if run.automation_id else None
        text = str(step["texte"])
        event = run.context.get("evenement")
        if isinstance(event, dict):
            detail = json.dumps(event, ensure_ascii=False)[:2000]
            text += "\n\nCe qui a déclenché l'automatisation :\n" + as_data(
                detail, origin=f"événement {event.get('type', '')}"
            )
        conversation_id = automation.conversation_id if automation else None
        reply: list[str] = []
        plans: list[str] = []
        async for event_out in self._chat.respond(
            text=text, conversation_id=conversation_id, channel="automation", learn=False
        ):
            if event_out.type == "start":
                conversation_id = str(event_out.data["conversation_id"])
            elif event_out.type == "delta":
                reply.append(str(event_out.data["text"]))
            elif event_out.type == "plan":
                plans.append(str(event_out.data["id"]))
            elif event_out.type == "error":
                # Modèle indisponible : le moteur de workflows réessaiera plus tard.
                raise UpstreamError(str(event_out.data.get("message", "réponse impossible")))
        if automation is not None and automation.conversation_id is None and conversation_id:
            await self._store.set_conversation(automation.id, conversation_id)
        return {
            "reponse": "".join(reply).strip(),
            "plans": plans,
            "conversation_id": conversation_id,
        }

    async def notify(self, step: dict[str, Any], run: RunRecord) -> dict[str, Any]:
        plans = [str(p) for p in run.context.get("plans", [])]
        body = str(step.get("texte") or run.context.get("reponse") or "C'est fait.")
        if plans:
            count = len(plans)
            body += (
                "\n\nUne action attend ta validation."
                if count == 1
                else f"\n\n{count} actions attendent ta validation."
            )
        kind = "rappel" if step.get("texte") else "automatisation"
        await self._notifier.notify(
            Notice(
                title=str(step.get("titre") or run.title),
                body=body,
                kind=kind,
                plans=tuple(plans),
                conversation_id=run.context.get("conversation_id"),
            )
        )
        return {"notifie": True}
