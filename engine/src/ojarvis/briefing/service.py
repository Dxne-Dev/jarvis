"""Le briefing du matin : à ta première session du jour, Jarvis résume ta journée à voix haute.

Ce qu'il rassemble : ton agenda du jour (Google Agenda), les pull requests et issues qui
t'attendent (GitHub), tes rappels du jour et ce que tes automatisations ont fait depuis
hier soir. Puis il en fait quelques phrases parlées, les dit si la voix est prête, et les
garde dans une conversation « Briefing du … ». Une source absente est simplement passée.

C'est un workflow : coupé par un arrêt, il reprend où il en était.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, time, timedelta, tzinfo
from typing import Any

from ojarvis.automations.store import AutomationStore
from ojarvis.context.engine import PERSONA, french_now
from ojarvis.conversations.store import ConversationStore
from ojarvis.core.clock import local_timezone, utc_now
from ojarvis.core.logs import get_logger
from ojarvis.events.bus import EventBus
from ojarvis.integrations.calendar_server import event_line, list_events
from ojarvis.integrations.connection import McpCallError
from ojarvis.integrations.google import GoogleAccount
from ojarvis.integrations.manager import IntegrationManager
from ojarvis.llm.errors import LLMError
from ojarvis.llm.router import ModelRouter
from ojarvis.llm.types import LLMRequest, Message
from ojarvis.notifications import Notice, Notifier
from ojarvis.settings_store import SettingsStore
from ojarvis.tools.guards import DATA_RULE, as_data
from ojarvis.voice.service import VoiceService
from ojarvis.workflows.engine import RunRecord, StepHandler, WorkflowEngine

log = get_logger(__name__)

STATE_KEY = "briefing.dernier_jour"
#: « Pendant la nuit » : depuis la veille à 20 h.
NIGHT_START = time(20, 0)
BRIEFING_RULES = (
    "Fais le briefing du matin de l'utilisateur, à voix haute : quatre à sept phrases, "
    "sans markdown ni liste, nombres et heures écrits comme on les dit. Salue-le, puis dis "
    "ce qui compte : son agenda du jour, les pull requests et issues qui l'attendent, ses "
    "rappels du jour, ce que ses automatisations ont fait cette nuit. Passe ce qui est vide "
    "ou indisponible sans t'y attarder ; n'invente rien."
)
_DAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
_MONTHS = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)


def day_title(moment: datetime) -> str:
    return f"Briefing du {_DAYS[moment.weekday()]} {moment.day} {_MONTHS[moment.month - 1]}"


class BriefingService:
    def __init__(
        self,
        *,
        settings: SettingsStore,
        workflows: WorkflowEngine,
        router: ModelRouter,
        conversations: ConversationStore,
        automations: AutomationStore,
        integrations: IntegrationManager,
        google: GoogleAccount,
        voice: VoiceService,
        notifier: Notifier,
        bus: EventBus,
        http: Any,
        clock: Callable[[], datetime] = utc_now,
        timezone: Callable[[], tzinfo] = local_timezone,
    ) -> None:
        self._settings = settings
        self._workflows = workflows
        self._router = router
        self._conversations = conversations
        self._automations = automations
        self._integrations = integrations
        self._google = google
        self._voice = voice
        self._notifier = notifier
        self._bus = bus
        self._http = http
        self._clock = clock
        self._timezone = timezone

    def handlers(self) -> dict[str, StepHandler]:
        return {
            "briefing_rassembler": self.collect,
            "briefing_rediger": self.compose,
            "briefing_dire": self.deliver,
        }

    # ------------------------------------------------------------------ déclenchement

    async def on_session_start(self, *, force: bool = False) -> RunRecord | None:
        """Première session du jour (l'app s'ouvre) : un briefing, une seule fois par jour."""
        prefs = await self._settings.get()
        if not prefs.briefing_enabled and not force:
            return None
        today = self._clock().astimezone(self._timezone()).date().isoformat()
        if not force and await self._settings.get_state(STATE_KEY) == today:
            return None
        # Noté tout de suite : deux fenêtres ouvertes en même temps ne font qu'un briefing.
        await self._settings.set_state(STATE_KEY, today)
        run = await self._workflows.submit(
            kind="briefing",
            title=day_title(self._clock().astimezone(self._timezone())),
            steps=[
                {"type": "briefing_rassembler"},
                {"type": "briefing_rediger"},
                {"type": "briefing_dire"},
            ],
            context={"jour": today},
        )
        log.info("briefing_started", day=today)
        return run

    # ------------------------------------------------------------------ étapes

    async def collect(self, step: dict[str, Any], run: RunRecord) -> dict[str, Any]:
        del step
        tz = self._timezone()
        now = self._clock().astimezone(tz)
        start_of_day = datetime.combine(now.date(), time(0), tzinfo=tz)
        sources: dict[str, str] = {}
        if self._google.connected:
            try:
                token = await self._google.access_token()
                events = await list_events(
                    self._http,
                    token,
                    start=start_of_day,
                    end=start_of_day + timedelta(days=1),
                    tz=tz,
                )
                sources["agenda"] = "\n".join(event_line(e, tz) for e in events) or "Rien."
            except Exception as exc:
                sources["agenda"] = f"(indisponible : {type(exc).__name__})"
        if self._integrations.configured("github"):
            sources["github"] = await self._github()
        reminders = []
        for automation in await self._automations.all():
            due = automation.next_run_at
            if automation.enabled and due is not None and due.astimezone(tz).date() == now.date():
                reminders.append(
                    f"{due.astimezone(tz):%H:%M} — {automation.name} ({automation.what})"
                )
        sources["rappels"] = "\n".join(reminders) or "Aucun."
        since = datetime.combine(now.date() - timedelta(days=1), NIGHT_START, tzinfo=tz)
        night = []
        for done in await self._workflows.runs(since=since.astimezone(), limit=30):
            if done.kind != "automation" or done.id == run.id:
                continue
            summary = str(done.context.get("reponse") or "")[:300]
            night.append(
                f"{done.created_at.astimezone(tz):%H:%M} {done.title} : {done.status}. {summary}"
            )
        sources["nuit"] = "\n".join(night) or "Aucune automatisation n'a tourné."
        return {"sources": sources}

    async def _github(self) -> str:
        parts = []
        for label, tool, query in (
            ("Revues demandées", "search_pull_requests", "is:open is:pr review-requested:@me"),
            ("Issues qui te sont confiées", "search_issues", "is:open is:issue assignee:@me"),
        ):
            try:
                text, is_error = await self._integrations.call("github", tool, {"query": query})
            except McpCallError as exc:
                parts.append(f"{label} : indisponible ({exc})")
                continue
            parts.append(f"{label} :\n{_titles(text) if not is_error else '(erreur)'}")
        return "\n\n".join(parts)

    async def compose(self, step: dict[str, Any], run: RunRecord) -> dict[str, Any]:
        del step
        sources: dict[str, str] = dict(run.context.get("sources", {}))
        tz = self._timezone()
        blocks = "\n\n".join(
            f"{name.capitalize()} :\n{as_data(text, origin=name)}" for name, text in sources.items()
        )
        request = LLMRequest(
            messages=[
                Message("system", f"{PERSONA}\n\n{DATA_RULE}\n\n{BRIEFING_RULES}"),
                Message("user", f"{french_now(self._clock(), tz)}\n\n{blocks}"),
            ],
            max_tokens=400,
        )
        try:
            result = await self._router.complete("voice", request)
            text = result.text.strip()
        except LLMError:
            log.warning("briefing_compose_failed")
            text = ""
        return {"texte": text or _fallback(sources)}

    async def deliver(self, step: dict[str, Any], run: RunRecord) -> dict[str, Any]:
        del step
        text = str(run.context.get("texte") or "")
        conversation = await self._conversations.create("app", title=run.title)
        await self._conversations.add_message(
            conversation.id, "assistant", text, meta={"briefing": run.id}
        )
        today = self._clock().astimezone(self._timezone()).date().isoformat()
        # Un briefing repris le lendemain (après un arrêt) n'est plus dit à voix haute.
        spoken = run.context.get("jour") == today and self._voice.say(text)
        await self._notifier.notify(
            Notice(run.title, text, kind="briefing", conversation_id=conversation.id)
        )
        await self._bus.publish(
            "briefing.delivered", {"conversation_id": conversation.id, "spoken": spoken}
        )
        return {"conversation_id": conversation.id, "dit": spoken}


def _titles(text: str) -> str:
    """Titres et dépôts d'une recherche GitHub (sinon le texte brut, tronqué)."""
    try:
        data = json.loads(text)
    except ValueError:
        return text[:1500]
    items = data.get("items", []) if isinstance(data, dict) else []
    lines = []
    for item in items[:10]:
        if not isinstance(item, dict):
            continue
        repo = str(item.get("repository_url", "")).rsplit("/repos/", 1)[-1]
        lines.append(f"- {item.get('title', '?')} ({repo}#{item.get('number', '?')})")
    total = data.get("total_count", len(lines)) if isinstance(data, dict) else len(lines)
    return f"{total} en tout\n" + "\n".join(lines) if lines else "Aucune."


def _fallback(sources: dict[str, str]) -> str:
    """Si le modèle ne répond pas : un briefing simple, sans formules."""
    parts = ["Bonjour. Voici ta journée."]
    for name, label in (("agenda", "Agenda"), ("rappels", "Rappels"), ("nuit", "Cette nuit")):
        if name in sources:
            first = sources[name].splitlines()[0] if sources[name] else ""
            parts.append(f"{label} : {first}")
    return " ".join(parts)
