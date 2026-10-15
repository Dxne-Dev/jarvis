"""Parler à Jarvis depuis ton téléphone, par Telegram (texte ou message vocal).

- Seul `TELEGRAM_ALLOWED_USER_ID` est servi : tout autre expéditeur est ignoré, et
  l'essai est journalisé (logs et événement `telegram.rejected`).
- Un message vocal est transcrit par Groq (français imposé), puis traité comme un texte.
- Un plan de niveau 2 proposé pendant l'échange arrive avec deux boutons, « Valider » et
  « Refuser ». Un plan de niveau 3 ne se valide jamais depuis Telegram : il attend dans
  l'app, où la double confirmation est possible.
- Les rappels et résultats des automatisations te parviennent aussi ici.

Le jeton du bot fait partie de l'adresse de l'API : aucune adresse n'est jamais écrite
dans les logs.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from ojarvis.agent.executor import DoubleConfirmationRequiredError, PlanExecutor
from ojarvis.agent.plans import PlanStore
from ojarvis.chat.service import ChatService
from ojarvis.core.errors import EngineError
from ojarvis.core.logs import get_logger
from ojarvis.events.bus import EventBus
from ojarvis.notifications import Notice, Notifier
from ojarvis.voice.stt import GroqTranscriber, SttError

log = get_logger(__name__)

API = "https://api.telegram.org"
POLL_TIMEOUT_S = 30
MAX_MESSAGE = 4000
#: Après ce silence, le message suivant ouvre une nouvelle conversation.
CONVERSATION_IDLE_S = 2 * 3600
IDLE_RETRY_S = 30.0


@dataclass
class TelegramStatus:
    configured: bool = False
    connected: bool = False
    bot: str | None = None
    last_error: str | None = None
    handled: int = 0
    rejected: int = 0


def _chunks(text: str) -> list[str]:
    text = text.strip() or "…"
    return [text[i : i + MAX_MESSAGE] for i in range(0, len(text), MAX_MESSAGE)]


class TelegramService:
    def __init__(
        self,
        *,
        http: httpx.AsyncClient,
        secret: Callable[[str], str | None],
        chat: ChatService,
        plans: PlanStore,
        executor: PlanExecutor,
        notifier: Notifier,
        bus: EventBus,
        transcriber: GroqTranscriber | None = None,
        api: str = API,
    ) -> None:
        self._http = http
        self._secret = secret
        self._chat = chat
        self._plans = plans
        self._executor = executor
        self._notifier = notifier
        self._bus = bus
        self._transcriber = transcriber
        self._api = api
        self._offset = 0
        self._task: asyncio.Task[None] | None = None
        self._conversation: tuple[str, float] | None = None
        self.status = TelegramStatus()

    # ------------------------------------------------------------------ configuration

    def _token(self) -> str | None:
        return self._secret("TELEGRAM_BOT_TOKEN") or None

    def _allowed(self) -> int | None:
        raw = (self._secret("TELEGRAM_ALLOWED_USER_ID") or "").strip()
        return int(raw) if raw.lstrip("-").isdigit() else None

    def _url(self, method: str) -> str:
        return f"{self._api}/bot{self._token()}/{method}"

    async def _call(self, method: str, **params: Any) -> Any:
        timeout = POLL_TIMEOUT_S + 10 if method == "getUpdates" else 20
        try:
            response = await self._http.post(self._url(method), json=params, timeout=timeout)
        except httpx.HTTPError as exc:
            # Jamais l'exception elle-même : son texte contient l'adresse, donc le jeton.
            raise ConnectionError(f"Telegram injoignable ({type(exc).__name__})") from None
        body = response.json() if response.content else {}
        if response.status_code != 200 or not body.get("ok"):
            raise ConnectionError(f"Telegram a refusé {method} (HTTP {response.status_code})")
        return body.get("result")

    # ------------------------------------------------------------------ cycle de vie

    async def start(self) -> None:
        self._notifier.add_channel("telegram", self._send_notice)
        self._task = asyncio.create_task(self._loop())

    async def close(self) -> None:
        self._notifier.remove_channel("telegram")
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task

    async def _loop(self) -> None:
        while True:
            if not (self._token() and self._allowed() is not None):
                self.status = TelegramStatus(configured=False)
                await asyncio.sleep(IDLE_RETRY_S)
                continue
            try:
                if not self.status.connected:
                    me = await self._call("getMe")
                    self.status.configured = True
                    self.status.connected = True
                    self.status.bot = str(me.get("username", ""))
                    self.status.last_error = None
                    log.info("telegram_connected", bot=self.status.bot)
                updates = await self._call(
                    "getUpdates",
                    offset=self._offset,
                    timeout=POLL_TIMEOUT_S,
                    allowed_updates=["message", "callback_query"],
                )
                for update in updates or []:
                    self._offset = max(self._offset, int(update["update_id"]) + 1)
                    await self.handle(update)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.status.connected = False
                self.status.last_error = str(exc)[:200]
                log.warning("telegram_poll_failed", error=type(exc).__name__)
                await asyncio.sleep(IDLE_RETRY_S)

    # ------------------------------------------------------------------ messages

    async def handle(self, update: dict[str, Any]) -> None:
        """Un message ou un clic sur un bouton (public pour les tests)."""
        if "callback_query" in update:
            await self._on_button(update["callback_query"])
            return
        message = update.get("message") or {}
        sender = (message.get("from") or {}).get("id")
        chat_id = (message.get("chat") or {}).get("id")
        if sender is None or sender != self._allowed() or not isinstance(chat_id, int):
            self.status.rejected += 1
            log.warning("telegram_rejected", sender=sender)
            await self._bus.publish("telegram.rejected", {"sender": sender})
            return
        text = str(message.get("text") or "").strip()
        kind = "texte"
        if not text and message.get("voice"):
            kind = "vocal"
            text = await self._transcribe(message["voice"], chat_id)
            if not text:
                return
        if not text:
            await self._send(chat_id, "Je comprends le texte et les messages vocaux.")
            return
        self.status.handled += 1
        await self._bus.publish("telegram.message", {"kind": kind, "text": text[:500]})
        await self._reply(chat_id, text)

    async def _transcribe(self, voice: dict[str, Any], chat_id: int) -> str:
        if self._transcriber is None or not self._transcriber.available:
            await self._send(
                chat_id, "Je ne peux pas écouter les messages vocaux : clé Groq absente."
            )
            return ""
        try:
            file = await self._call("getFile", file_id=voice["file_id"])
            response = await self._http.get(
                f"{self._api}/file/bot{self._token()}/{file['file_path']}", timeout=30
            )
            text = await self._transcriber.transcribe_file(
                response.content, "message.ogg", str(voice.get("mime_type") or "audio/ogg")
            )
        except (ConnectionError, SttError, httpx.HTTPError, KeyError) as exc:
            log.warning("telegram_voice_failed", error=type(exc).__name__)
            await self._send(chat_id, "Je n'ai pas pu écouter ce message vocal.")
            return ""
        if not text:
            await self._send(chat_id, "Je n'ai rien entendu dans ce message.")
            return ""
        await self._send(chat_id, f"🎙️ « {text} »")
        return text

    def _conversation_id(self) -> str | None:
        if self._conversation is None:
            return None
        conversation_id, last = self._conversation
        return conversation_id if time.monotonic() - last < CONVERSATION_IDLE_S else None

    async def _reply(self, chat_id: int, text: str) -> None:
        reply: list[str] = []
        plans: list[dict[str, Any]] = []
        conversation_id = self._conversation_id()
        try:
            async for event in self._chat.respond(
                text=text, conversation_id=conversation_id, channel="telegram"
            ):
                if event.type == "start":
                    conversation_id = str(event.data["conversation_id"])
                elif event.type == "delta":
                    reply.append(str(event.data["text"]))
                elif event.type == "plan":
                    plans.append(event.data)
                elif event.type == "error":
                    reply.append(f"\n(Je n'ai pas pu finir : {event.data.get('message')})")
        except EngineError as exc:
            reply = [f"Je n'ai pas pu répondre : {exc.message}"]
        if conversation_id:
            self._conversation = (conversation_id, time.monotonic())
        await self._send(chat_id, "".join(reply))
        for plan in plans:
            await self._offer(chat_id, plan)

    # ------------------------------------------------------------------ plans

    async def _offer(self, chat_id: int, plan: dict[str, Any]) -> None:
        if plan.get("status") != "proposed":
            return
        steps = "\n".join(f"{s['position']}. {s['description']}" for s in plan.get("steps", []))
        text = f"Plan : {plan.get('title')}\n{steps}"
        if int(plan.get("max_level", 1)) >= 3:
            await self._send(
                chat_id,
                text + "\n\nIl contient une destruction : valide-le dans l'app "
                "(double confirmation), jamais depuis Telegram.",
            )
            return
        warning = (
            "\n\n⚠️ Proposé après la lecture d'un contenu externe." if plan.get("tainted") else ""
        )
        await self._call(
            "sendMessage",
            chat_id=chat_id,
            text=text + warning,
            reply_markup={
                "inline_keyboard": [
                    [
                        {"text": "✅ Valider", "callback_data": f"ok:{plan['id']}"},
                        {"text": "✖️ Refuser", "callback_data": f"non:{plan['id']}"},
                    ]
                ]
            },
        )

    async def _on_button(self, query: dict[str, Any]) -> None:
        sender = (query.get("from") or {}).get("id")
        if sender is None or sender != self._allowed():
            self.status.rejected += 1
            log.warning("telegram_rejected", sender=sender)
            await self._bus.publish("telegram.rejected", {"sender": sender, "bouton": True})
            return
        decision, _, plan_id = str(query.get("data", "")).partition(":")
        answer = "C'est noté."
        try:
            if decision == "ok":
                await self._executor.approve(plan_id, channel="telegram")
                answer = "Validé : Jarvis s'y met."
            elif decision == "non":
                await self._executor.refuse(plan_id, channel="telegram")
                answer = "Refusé : rien ne sera fait."
        except DoubleConfirmationRequiredError:
            answer = "Destruction : à valider dans l'app (double confirmation)."
        except EngineError as exc:
            answer = exc.message
        with contextlib.suppress(ConnectionError):
            await self._call(
                "answerCallbackQuery", callback_query_id=query["id"], text=answer[:190]
            )
        message = query.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        if chat_id is not None and message.get("message_id") is not None:
            with contextlib.suppress(ConnectionError):
                await self._call(
                    "editMessageText",
                    chat_id=chat_id,
                    message_id=message["message_id"],
                    text=f"{message.get('text', '')}\n\n→ {answer}"[:MAX_MESSAGE],
                )

    # ------------------------------------------------------------------ envoi

    async def _send(self, chat_id: int | None, text: str) -> None:
        if chat_id is None:
            return
        for chunk in _chunks(text):
            await self._call("sendMessage", chat_id=chat_id, text=chunk)

    async def _send_notice(self, notice: Notice) -> None:
        """Rappels et résultats d'automatisations : aussi sur le téléphone."""
        allowed = self._allowed()
        if not (self.status.connected and allowed is not None):
            return
        await self._send(allowed, f"{notice.title}\n\n{notice.body}")
        for plan_id in notice.plans:
            plan = await self._plans.get(plan_id)
            await self._offer(
                allowed,
                {
                    "id": plan.id,
                    "title": plan.title,
                    "status": plan.status,
                    "max_level": plan.max_level,
                    "tainted": plan.tainted,
                    "steps": [
                        {"position": s.position, "description": s.description} for s in plan.steps
                    ],
                },
            )
