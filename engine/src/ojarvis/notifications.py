"""Prévenir l'utilisateur : dans l'app (et sur le bureau), et sur ses autres canaux.

Un rappel, le résultat d'une automatisation, une action préparée qui attend ta validation :
tout passe par ici. L'interface reçoit l'événement `notification` ; Telegram, s'il est
branché, reçoit le même message.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from ojarvis.core.logs import get_logger
from ojarvis.events.bus import EventBus

log = get_logger(__name__)


@dataclass(frozen=True)
class Notice:
    title: str
    body: str
    kind: str = "info"  # rappel | automatisation | validation | info
    plans: tuple[str, ...] = field(default_factory=tuple)
    conversation_id: str | None = None


Channel = Callable[[Notice], Awaitable[None]]


class Notifier:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._channels: dict[str, Channel] = {}

    def add_channel(self, name: str, send: Channel) -> None:
        self._channels[name] = send

    def remove_channel(self, name: str) -> None:
        self._channels.pop(name, None)

    async def notify(self, notice: Notice) -> None:
        await self._bus.publish(
            "notification",
            {
                "title": notice.title[:200],
                "body": notice.body[:2000],
                "kind": notice.kind,
                "plans": list(notice.plans),
                "conversation_id": notice.conversation_id,
            },
        )
        for name, send in list(self._channels.items()):
            try:
                await send(notice)
            except Exception:
                log.warning("notification_channel_failed", channel=name)
