"""Les suggestions de Jarvis : apprises de tes demandes, anticipées de tes habitudes.

Accepter une suggestion ouvre une conversation où Jarvis s'y met (une automatisation ou un
skill passent alors par un plan que tu valides) ; l'écarter la range pour de bon.
"""

from __future__ import annotations

import asyncio
import contextlib

from ojarvis.anticipation.predictor import Predictor
from ojarvis.anticipation.repetition import RepetitionWatcher
from ojarvis.anticipation.store import Suggestion, SuggestionStore
from ojarvis.chat.service import ChatService
from ojarvis.conversations.store import ConversationStore
from ojarvis.core.errors import NotFoundError
from ojarvis.core.logs import get_logger
from ojarvis.events.bus import EventBus, Subscription

log = get_logger(__name__)

#: L'anticipation repasse toutes les 6 heures (la première fois, une minute après le démarrage).
EVERY_S = 6 * 3600
FIRST_S = 60.0


class AnticipationService:
    def __init__(
        self,
        *,
        store: SuggestionStore,
        watcher: RepetitionWatcher,
        predictor: Predictor,
        chat: ChatService,
        conversations: ConversationStore,
        bus: EventBus,
    ) -> None:
        self.store = store
        self._watcher = watcher
        self._predictor = predictor
        self._chat = chat
        self._conversations = conversations
        self._bus = bus
        self._subscription: Subscription | None = None
        self._loop: asyncio.Task[None] | None = None
        self._turns: set[asyncio.Task[None]] = set()

    def start(self, *, periodic: bool = True) -> None:
        self._subscription = self._bus.subscribe("chat.completed", self._watcher.on_completed)
        if periodic:
            self._loop = asyncio.create_task(self._periodic())

    async def _periodic(self) -> None:
        await asyncio.sleep(FIRST_S)
        while True:
            try:
                made = await self._predictor.run()
                if made:
                    log.info("suggestions_made", count=len(made))
            except Exception:
                log.exception("anticipation_failed")
            await asyncio.sleep(EVERY_S)

    async def anticipate(self) -> list[Suggestion]:
        return await self._predictor.run()

    async def accept(self, suggestion_id: str, option_id: str) -> Suggestion:
        suggestion = await self.store.get(suggestion_id)
        option = next((o for o in suggestion.options if o.id == option_id), None)
        if option is None:
            raise NotFoundError("Option inconnue pour cette suggestion.")
        conversation = await self._conversations.create("app")
        decided = await self.store.decide(
            suggestion_id, "acceptee", conversation_id=conversation.id
        )
        turn = asyncio.create_task(self._ask(option.prompt, conversation.id))
        self._turns.add(turn)
        turn.add_done_callback(self._turns.discard)
        return decided

    async def _ask(self, prompt: str, conversation_id: str) -> None:
        try:
            async for _ in self._chat.respond(text=prompt, conversation_id=conversation_id):
                pass
        except Exception:
            log.exception("suggestion_turn_failed")

    async def dismiss(self, suggestion_id: str) -> Suggestion:
        return await self.store.decide(suggestion_id, "ecartee")

    async def drain(self) -> None:
        """Attend les conversations lancées par une suggestion (tests, arrêt propre)."""
        while self._turns:
            await asyncio.gather(*list(self._turns), return_exceptions=True)

    async def close(self) -> None:
        if self._subscription is not None:
            self._subscription.close()
        tasks = [t for t in [self._loop, *self._turns] if t is not None]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
