"""Un tour de conversation, du message de l'utilisateur à la réponse diffusée en direct.

Utilisé par l'interface (texte), la voix et Telegram. Après la réponse, sans faire
attendre l'utilisateur : titre de la conversation, vectorisation de l'échange et
extraction des faits durables (visibles et modifiables dans l'écran Mémoire).
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

from ojarvis.agent.loop import (
    MAX_TOOL_ROUNDS,
    Agent,
    AgentTurn,
    plan_summary,
    urls_in,
)
from ojarvis.context.engine import BuiltContext, ContextEngine
from ojarvis.conversations.store import DEFAULT_TITLE, ConversationStore, MessageRecord
from ojarvis.core.errors import InvalidInputError
from ojarvis.core.logs import get_logger
from ojarvis.events.bus import EventBus
from ojarvis.llm.errors import LLMError
from ojarvis.llm.router import ModelRouter, RoutedStream
from ojarvis.llm.structured import generate_structured
from ojarvis.llm.types import (
    LLMRequest,
    Message,
    ReasoningDelta,
    RouteInfo,
    StreamEnd,
    TaskType,
    TextDelta,
    ToolCall,
    ToolCallReady,
    Usage,
)
from ojarvis.memory.graph import GraphStore
from ojarvis.memory.store import MemoryStore
from ojarvis.security.redaction import REDACTOR
from ojarvis.tracing.tracer import Tracer

log = get_logger(__name__)

MAX_INPUT_CHARS = 8000
Channel = Literal["app", "voice", "telegram", "automation"]


@dataclass(frozen=True, slots=True)
class ChatEvent:
    type: str  # start | context | route | delta | tool | plan | done | error
    data: dict[str, Any] = field(default_factory=dict)


class ExtractedFact(BaseModel):
    type: Literal["fait", "preference", "profil"]
    contenu: str = Field(min_length=3, max_length=400)
    confiance: float = Field(ge=0, le=1)
    remplace: int | None = Field(default=None, description="id d'un souvenir que ce fait corrige")


class ExtractedEntity(BaseModel):
    nom: str = Field(min_length=1, max_length=120)
    type: Literal["moi", "personne", "projet", "evenement", "lieu", "organisation", "sujet"]
    description: str | None = Field(default=None, max_length=300)


class ExtractedRelation(BaseModel):
    source: str = Field(min_length=1, max_length=120)
    lien: str = Field(min_length=2, max_length=80)
    cible: str = Field(min_length=1, max_length=120)


class Extraction(BaseModel):
    faits: list[ExtractedFact] = Field(default_factory=list, max_length=8)
    entites: list[ExtractedEntity] = Field(default_factory=list, max_length=10)
    relations: list[ExtractedRelation] = Field(default_factory=list, max_length=10)


EXTRACTION_PROMPT = (
    "Tu tiens à jour la mémoire de Jarvis sur l'utilisateur. Lis l'échange ci-dessous et "
    "relève seulement les informations durables que l'utilisateur donne sur lui-même : "
    "identité, goûts, habitudes, projets, proches, contraintes. Ignore le temporaire (météo du "
    "jour, humeur passagère), les suppositions et les connaissances générales. Chaque fait est "
    "une phrase autonome à la troisième personne ; désigne l'utilisateur par son prénom s'il "
    "est connu, sinon « L'utilisateur ». « profil » = identité stable (nom, ville, métier) ; "
    "« preference » = goût ou façon de faire ; « fait » = le reste. Si un fait corrige un "
    "souvenir existant, mets son id dans « remplace ». Un prénom ne se retient que s'il est "
    "dit clairement (« je m'appelle… ») ; une phrase confuse ou incomplète ne donne rien. "
    "Relève aussi, pour la mémoire graphe, les entités durables de sa vie (personnes, projets, "
    "événements, lieux, organisations, sujets qu'il étudie) et les relations entre elles : "
    "l'utilisateur est l'entité « moi » (type moi) ; une relation est courte, au présent "
    "(« travaille sur », « connaît », « habite à », « participe à », « apprend ») et relie deux "
    "entités de la liste. Réutilise exactement les noms déjà connus. "
    "S'il n'y a rien à retenir, renvoie des listes vides."
)
TITLE_PROMPT = (
    "Donne un titre de trois à six mots, en français, sans guillemets ni point final, "
    "pour la conversation suivante."
)


_TITLE_TRIM = " \t\n.!?:;«»\"'“”‘’"


def clean_title(raw: str) -> str:
    """Retire guillemets, ponctuation finale et espaces, dans n'importe quel ordre."""
    first_line = raw.strip().splitlines()[0] if raw.strip() else ""
    return " ".join(first_line.strip(_TITLE_TRIM).split())[:80]


@dataclass
class _Round:
    """Un appel au modèle dans un tour : ce qu'il a dit, pensé et demandé."""

    said: list[str] = field(default_factory=list)
    reasoning: list[str] = field(default_factory=list)
    calls: list[ToolCall] = field(default_factory=list)


@dataclass
class _Turn:
    """État d'un tour en cours (réponse partielle, route, jetons, chronomètre)."""

    assistant: MessageRecord
    start: float
    parts: list[str] = field(default_factory=list)
    route: RouteInfo | None = None
    usage: Usage = field(default_factory=Usage)
    state: RoutedStream = field(default_factory=RoutedStream)
    first_token_ms: float | None = None
    trace_id: str = ""
    finished: bool = False
    agent: AgentTurn = field(default_factory=AgentTurn)


def _context_event(context: BuiltContext) -> dict[str, Any]:
    return {
        "budget": context.budget,
        "used": context.used,
        "items": [
            {"kind": i.kind, "preview": i.text[:90], "kept": i.kept}
            for i in context.items
            if i.kind != "systeme"
        ],
    }


class ChatService:
    def __init__(
        self,
        *,
        conversations: ConversationStore,
        memory: MemoryStore,
        context: ContextEngine,
        router: ModelRouter,
        tracer: Tracer,
        bus: EventBus,
        learn: bool = True,
        agent: Agent | None = None,
        graph: GraphStore | None = None,
    ) -> None:
        self._conversations = conversations
        self._memory = memory
        self._graph = graph
        self._context = context
        self._router = router
        self._tracer = tracer
        self._bus = bus
        self.learn = learn
        self._agent = agent
        self._background: set[asyncio.Task[None]] = set()

    async def respond(
        self,
        *,
        text: str,
        conversation_id: str | None = None,
        channel: Channel = "app",
        learn: bool = True,
    ) -> AsyncGenerator[ChatEvent]:
        """Un tour de conversation, en flux. `learn=False` : rien n'est retenu de ce tour
        (par exemple une transcription vocale douteuse)."""
        # Une clé collée par erreur n'est ni enregistrée en clair ni envoyée au modèle.
        cleaned = REDACTOR.redact(text.strip())
        if not cleaned or len(cleaned) > MAX_INPUT_CHARS:
            raise InvalidInputError("Le message doit faire entre 1 et 8000 caractères.")
        if conversation_id:
            conversation = await self._conversations.get(conversation_id)
        else:
            conversation = await self._conversations.create(channel)
            await self._bus.publish(
                "conversation.created", {"id": conversation.id, "channel": channel}
            )
        history = await self._conversations.messages(conversation.id, limit=60)
        user = await self._conversations.add_message(conversation.id, "user", cleaned)
        assistant = await self._conversations.add_message(
            conversation.id, "assistant", "", status="streaming"
        )
        turn = _Turn(assistant=assistant, start=time.perf_counter())
        yield ChatEvent(
            "start",
            {
                "conversation_id": conversation.id,
                "user_message_id": user.id,
                "assistant_message_id": assistant.id,
            },
        )
        try:
            async with self._tracer.trace(
                f"Tour {'vocal' if channel == 'voice' else 'de conversation'}",
                kind="voice" if channel == "voice" else "chat",
                meta={"conversation_id": conversation.id, "channel": channel},
                reuse=True,
            ) as trace:
                turn.trace_id = trace.id
                async with self._tracer.span("contexte", kind="context") as span:
                    context = await self._context.build(
                        conversation_id=conversation.id,
                        user_text=cleaned,
                        channel=channel,
                        history=history,
                    )
                    span.set(**context.summary())
                yield ChatEvent("context", _context_event(context))
                request = LLMRequest(
                    messages=context.messages, max_tokens=500 if channel == "voice" else 4000
                )
                task: TaskType = "voice" if channel == "voice" else "chat"
                try:
                    async for event in self._reply(
                        task, request, turn, conversation_id=conversation.id, user_text=cleaned
                    ):
                        yield event
                except LLMError as error:
                    trace.fail(error.public)
                    await self._finish(turn, "error")
                    yield ChatEvent("error", {"message": error.public, "partial": bool(turn.parts)})
                    return
                await self._memory.touch(context.memory_ids)
                record = await self._finish(turn, "ok")
                yield ChatEvent("done", self._done_event(conversation.id, record, turn))
                await self._bus.publish(
                    "chat.completed",
                    {
                        "conversation_id": conversation.id,
                        "message_id": record.id,
                        "channel": channel,
                    },
                )
                self._after(
                    conversation.id,
                    conversation.title == DEFAULT_TITLE and not history,
                    user,
                    record,
                    learn=learn,
                )
        finally:
            if not turn.finished:
                # Interrompu (client parti, ou coupé par la voix) : on garde ce qui a été dit.
                with contextlib.suppress(Exception):
                    await self._finish(turn, "interrupted")

    async def _reply(
        self,
        task: TaskType,
        request: LLMRequest,
        turn: _Turn,
        *,
        conversation_id: str,
        user_text: str,
    ) -> AsyncIterator[ChatEvent]:
        """Réponse du modèle ; s'il appelle des outils, on les traite et il reprend."""
        agent = self._agent
        if agent is not None:
            turn.agent.known_urls |= urls_in(user_text)
            request.tools = agent.specs()
            system = request.messages[0]
            request.messages[0] = Message("system", f"{system.content}\n\n{agent.rules()}")
        for rounds in range(MAX_TOOL_ROUNDS + 1):
            step = _Round()
            async for event in self._stream_round(task, request, turn, step):
                yield event
            if not step.calls or agent is None:
                return
            if rounds == MAX_TOOL_ROUNDS:
                log.warning("tool_rounds_exhausted", rounds=rounds)
                return
            request.messages.append(
                Message(
                    "assistant",
                    "".join(step.said),
                    tool_calls=tuple(step.calls),
                    reasoning="".join(step.reasoning) or None,
                    provider=turn.route.provider if turn.route else None,
                )
            )
            for call in step.calls:
                async for event in self._run_tool(
                    agent, call, request, turn, conversation_id=conversation_id, user_text=user_text
                ):
                    yield event

    async def _stream_round(
        self, task: TaskType, request: LLMRequest, turn: _Turn, step: _Round
    ) -> AsyncIterator[ChatEvent]:
        """Un appel au modèle : texte diffusé au fil de l'eau, appels d'outils mis de côté."""
        async for event in self._router.stream_traced(task, request, state=turn.state):
            if isinstance(event, RouteInfo):
                turn.route = event
                yield ChatEvent(
                    "route",
                    {
                        "provider": event.provider,
                        "model": event.model,
                        "fallback_from": event.fallback_from,
                    },
                )
            elif isinstance(event, TextDelta):
                if turn.first_token_ms is None:
                    turn.first_token_ms = (time.perf_counter() - turn.start) * 1000
                text = event.text
                if not step.said and turn.parts and not turn.parts[-1].endswith(("\n", " ")):
                    text = "\n\n" + text  # texte d'un nouveau tour, après des outils
                step.said.append(text)
                turn.parts.append(text)
                yield ChatEvent("delta", {"text": text})
            elif isinstance(event, ReasoningDelta):
                step.reasoning.append(event.text)
            elif isinstance(event, ToolCallReady):
                step.calls.append(event.call)
            elif isinstance(event, StreamEnd):
                turn.usage = Usage(
                    input_tokens=turn.usage.input_tokens + event.usage.input_tokens,
                    output_tokens=turn.usage.output_tokens + event.usage.output_tokens,
                    cached_input_tokens=turn.usage.cached_input_tokens
                    + event.usage.cached_input_tokens,
                )

    async def _run_tool(
        self,
        agent: Agent,
        call: ToolCall,
        request: LLMRequest,
        turn: _Turn,
        *,
        conversation_id: str,
        user_text: str,
    ) -> AsyncIterator[ChatEvent]:
        yield ChatEvent(
            "tool",
            {
                "id": call.id,
                "name": call.name,
                "description": agent.describe(call),
                "status": "running",
            },
        )
        async with self._tracer.span(f"outil {call.name}", kind="tool") as span:
            outcome = await agent.handle(
                call, turn.agent, conversation_id=conversation_id, request=user_text
            )
            span.set(status=outcome.event.get("status"), error=outcome.event.get("error"))
        yield ChatEvent("tool", outcome.event)
        if outcome.plan is not None:
            yield ChatEvent("plan", plan_summary(outcome.plan))
        request.messages.append(
            Message("tool", outcome.content, tool_call_id=call.id, is_error=outcome.is_error)
        )

    def _done_event(
        self, conversation_id: str, record: MessageRecord, turn: _Turn
    ) -> dict[str, Any]:
        return {
            "conversation_id": conversation_id,
            "message_id": record.id,
            "provider": turn.route.provider if turn.route else None,
            "model": turn.route.model if turn.route else None,
            "tokens_in": turn.usage.input_tokens,
            "tokens_out": turn.usage.output_tokens,
            "cost_usd": self._router.cost(turn.state.route, turn.usage),
            "latency_ms": record.latency_ms,
            "first_token_ms": round(turn.first_token_ms, 1) if turn.first_token_ms else None,
            "trace_id": turn.trace_id,
            "plans": list(turn.agent.plans),
        }

    async def _finish(self, turn: _Turn, status: str) -> MessageRecord:
        turn.finished = True
        route = turn.route
        return await self._conversations.finish_message(
            turn.assistant.id,
            content=REDACTOR.redact("".join(turn.parts).strip()),
            status=status,
            provider=route.provider if route else None,
            model=route.model if route else None,
            tokens_in=turn.usage.input_tokens or None,
            tokens_out=turn.usage.output_tokens or None,
            cost_usd=self._router.cost(turn.state.route, turn.usage),
            latency_ms=round((time.perf_counter() - turn.start) * 1000, 1),
            trace_id=turn.trace_id or None,
            meta=self._meta(turn),
        )

    @staticmethod
    def _meta(turn: _Turn) -> dict[str, Any] | None:
        """Outils utilisés et plans proposés : l'interface les affiche sous la réponse."""
        if not turn.agent.tools and not turn.agent.plans:
            return None
        return {"tools": turn.agent.tools, "plans": turn.agent.plans}

    # ------------------------------------------------------------------ après la réponse

    def _after(
        self,
        conversation_id: str,
        needs_title: bool,
        user: MessageRecord,
        reply: MessageRecord,
        *,
        learn: bool = True,
    ) -> None:
        task = asyncio.create_task(
            self._learn_from(conversation_id, needs_title, user, reply, learn=learn)
        )
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def _learn_from(
        self,
        conversation_id: str,
        needs_title: bool,
        user: MessageRecord,
        reply: MessageRecord,
        *,
        learn: bool = True,
    ) -> None:
        await self._conversations.index_exchange(user, reply)
        if needs_title:
            await self._title(conversation_id, user, reply)
        if self.learn and learn:
            await self._extract(user, reply)

    async def _title(self, conversation_id: str, user: MessageRecord, reply: MessageRecord) -> None:
        try:
            result = await self._router.complete(
                "title",
                LLMRequest(
                    messages=[
                        Message("system", TITLE_PROMPT),
                        Message(
                            "user", f"Utilisateur : {user.content}\nJarvis : {reply.content}"[:3000]
                        ),
                    ],
                    max_tokens=30,
                ),
            )
        except LLMError:
            log.warning("title_generation_failed")
            return
        title = clean_title(result.text)
        if title:
            await self._conversations.rename(conversation_id, title[:80])
            await self._bus.publish("conversation.updated", {"id": conversation_id})

    async def _extract(self, user: MessageRecord, reply: MessageRecord) -> None:
        known = await self._memory.search(user.content, k=8)
        known_lines = "\n".join(
            f"- id {h.record.id} [{h.record.kind}] {h.record.content}" for h in known
        )
        names = await self._graph.known_names() if self._graph else []
        entity_lines = ", ".join(f"{n} ({k})" for n, k in names)
        prompt = (
            f"Souvenirs existants proches :\n{known_lines or '(aucun)'}\n\n"
            f"Entités déjà connues : {entity_lines or '(aucune)'}\n\n"
            f"Échange :\nUtilisateur : {user.content}\nJarvis : {reply.content}"
        )[:6000]
        try:
            extraction = await generate_structured(
                self._router,
                "extract",
                [Message("system", EXTRACTION_PROMPT), Message("user", prompt)],
                Extraction,
            )
        except LLMError:
            log.warning("memory_extraction_failed")
            return
        known_ids = {h.record.id for h in known}
        for fact in extraction.faits:
            if fact.confiance < 0.6:
                continue
            if fact.remplace is not None and fact.remplace in known_ids:
                await self._memory.update(fact.remplace, content=fact.contenu, kind=fact.type)
            else:
                await self._memory.add(
                    fact.type,
                    fact.contenu,
                    source="conversation",
                    source_message_id=user.id,
                    confidence=fact.confiance,
                )
        if self._graph is not None and (extraction.entites or extraction.relations):
            await self._graph.remember(
                [(e.nom, e.type, e.description) for e in extraction.entites],
                [(r.source, r.lien, r.cible) for r in extraction.relations],
            )

    async def drain(self) -> None:
        """Attend la fin des apprentissages en cours (tests, arrêt propre)."""
        while self._background:
            await asyncio.gather(*list(self._background), return_exceptions=True)

    async def close(self) -> None:
        for task in list(self._background):
            task.cancel()
        await asyncio.gather(*list(self._background), return_exceptions=True)
