"""Le serveur MCP Google Agenda de Jarvis (quand celui de Google n'est pas disponible).

Trois outils, annotés pour les niveaux de permission : lister les événements (lecture),
créer un événement (action), supprimer un événement (destruction). Il parle à l'API
Google Agenda v3 avec le jeton de ton compte ; les heures sont celles de ton fuseau.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any
from urllib.parse import quote

import httpx

from ojarvis.core.clock import local_timezone

API = "https://www.googleapis.com/calendar/v3"


def _parse_day(value: str | None, tz: tzinfo) -> datetime:
    if not value:
        return datetime.combine(datetime.now(tz).date(), time(0), tzinfo=tz)
    parsed = datetime.fromisoformat(value)
    if isinstance(parsed, datetime) and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed


def event_line(event: dict[str, Any], tz: tzinfo) -> str:
    start = event.get("start", {})
    end = event.get("end", {})
    title = event.get("summary") or "(sans titre)"
    where = f" — {event['location']}" if event.get("location") else ""
    if "dateTime" in start:
        begin = datetime.fromisoformat(start["dateTime"]).astimezone(tz)
        finish = datetime.fromisoformat(end.get("dateTime", start["dateTime"])).astimezone(tz)
        when = f"{begin:%d/%m %H:%M}–{finish:%H:%M}"
    else:
        when = f"{date.fromisoformat(start.get('date', '1970-01-01')):%d/%m} (journée)"
    return f"{when} {title}{where} [id {event.get('id', '?')}]"


async def list_events(
    http: httpx.AsyncClient,
    token: str,
    *,
    start: datetime,
    end: datetime,
    calendar: str = "primary",
    tz: tzinfo,
) -> list[dict[str, Any]]:
    response = await http.get(
        f"{API}/calendars/{quote(calendar, safe='@.')}/events",
        params={
            "timeMin": start.isoformat(),
            "timeMax": end.isoformat(),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": "50",
            "timeZone": getattr(tz, "key", "UTC"),
        },
        headers={"Authorization": f"Bearer {token}"},
        timeout=20.0,
    )
    response.raise_for_status()
    items = response.json().get("items", [])
    return [i for i in items if isinstance(i, dict)]


def build_server(http: httpx.AsyncClient, token: Callable[[], Awaitable[str]]) -> Any:
    from mcp.server.mcpserver import MCPServer  # noqa: PLC0415
    from mcp.types import ToolAnnotations  # noqa: PLC0415

    server = MCPServer("agenda-jarvis")

    @server.tool(annotations=ToolAnnotations(read_only_hint=True))
    async def lister_evenements(
        debut: str | None = None, fin: str | None = None, calendrier: str = "primary"
    ) -> str:
        """Liste les événements entre deux dates (AAAA-MM-JJ ou AAAA-MM-JJTHH:MM, heure
        locale). Sans dates : aujourd'hui."""
        tz = local_timezone()
        start = _parse_day(debut, tz)
        end = _parse_day(fin, tz) if fin else start + timedelta(days=1)
        events = await list_events(
            http, await token(), start=start, end=end, calendar=calendrier, tz=tz
        )
        return "\n".join(event_line(e, tz) for e in events) or "Aucun événement."

    @server.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False))
    async def creer_evenement(
        titre: str, debut: str, fin: str, description: str = "", lieu: str = ""
    ) -> str:
        """Crée un événement (heures locales, AAAA-MM-JJTHH:MM)."""
        tz = local_timezone()
        zone = getattr(tz, "key", "UTC")
        body = {
            "summary": titre,
            "description": description,
            "location": lieu,
            "start": {"dateTime": _parse_day(debut, tz).isoformat(), "timeZone": zone},
            "end": {"dateTime": _parse_day(fin, tz).isoformat(), "timeZone": zone},
        }
        response = await http.post(
            f"{API}/calendars/primary/events",
            json=body,
            headers={"Authorization": f"Bearer {await token()}"},
            timeout=20.0,
        )
        response.raise_for_status()
        return f"Événement créé : {event_line(response.json(), tz)}"

    @server.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True))
    async def supprimer_evenement(identifiant: str) -> str:
        """Supprime un événement de l'agenda principal."""
        response = await http.delete(
            f"{API}/calendars/primary/events/{quote(identifiant, safe='')}",
            headers={"Authorization": f"Bearer {await token()}"},
            timeout=20.0,
        )
        response.raise_for_status()
        return "Événement supprimé."

    return server
