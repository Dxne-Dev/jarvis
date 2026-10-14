from __future__ import annotations

from pathlib import Path

import pytest

from ojarvis.core.clock import utc_now
from ojarvis.core.context import correlation_id_var
from ojarvis.core.errors import InvalidInputError
from ojarvis.db.engine import Database
from ojarvis.db.migrate import upgrade_to_head
from ojarvis.db.models import Setting
from ojarvis.events.bus import EventBus
from ojarvis.settings_store import SettingsStore
from ojarvis.tracing.tracer import TraceQueries, Tracer


@pytest.fixture
def db(tmp_path: Path) -> Database:
    db_path = tmp_path / "t.db"
    upgrade_to_head(db_path)
    return Database(db_path)


async def test_trace_with_nested_spans(db: Database) -> None:
    bus = EventBus()
    tracer = Tracer(db, bus)
    async with (
        tracer.trace("tour de chat", kind="chat", meta={"canal": "texte"}) as trace,
        tracer.span("contexte", kind="context") as outer,
        tracer.span("appel LLM", kind="llm", model="deepseek-flash") as inner,
    ):
        inner.set(tokens_in=120, tokens_out=40, cost_usd=0.0001)
    assert inner.parent_id == outer.id
    found = await TraceQueries(db).get(trace.id)
    assert found is not None
    record, spans = found
    assert record.status == "ok"
    assert record.duration_ms is not None
    assert record.meta == {"canal": "texte"}
    by_name = {s.name: s for s in spans}
    assert by_name["appel LLM"].attributes["tokens_in"] == 120
    assert by_name["appel LLM"].parent_id == by_name["contexte"].id
    summaries = await TraceQueries(db).recent()
    assert summaries[0].span_count == 2


async def test_errors_mark_trace_and_span(db: Database) -> None:
    tracer = Tracer(db, EventBus())
    trace_ids: list[str] = []

    async def failing() -> None:
        async with tracer.trace("échec") as trace, tracer.span("étape"):
            trace_ids.append(trace.id)
            raise ValueError("cassé")

    with pytest.raises(ValueError, match="cassé"):
        await failing()
    trace_id = trace_ids[0]
    found = await TraceQueries(db).get(trace_id)
    assert found is not None
    record, spans = found
    assert record.status == "error"
    assert record.error is not None
    assert "cassé" in record.error
    assert spans[0].status == "error"


async def test_span_outside_trace_opens_one(db: Database) -> None:
    tracer = Tracer(db, EventBus())
    async with tracer.span("isolée", kind="tool") as span:
        span.set(ok=True)
    summaries = await TraceQueries(db).recent()
    assert len(summaries) == 1
    assert summaries[0].name == "isolée"
    assert summaries[0].span_count == 1


async def test_trace_keeps_existing_correlation_id(db: Database) -> None:
    token = correlation_id_var.set("abc123")
    try:
        async with Tracer(db, EventBus()).trace("t") as trace:
            assert trace.correlation_id == "abc123"
    finally:
        correlation_id_var.reset(token)


async def test_trace_events_are_published(db: Database) -> None:
    bus = EventBus()
    tracer = Tracer(db, bus)
    async with bus.stream("trace.*") as queue:
        async with tracer.trace("t"), tracer.span("s"):
            pass
        types = [queue.get_nowait().type for _ in range(queue.qsize())]
    assert types == ["trace.span", "trace.finished"]


async def test_get_unknown_trace(db: Database) -> None:
    assert await TraceQueries(db).get("absent") is None


async def test_settings_defaults_and_update(db: Database) -> None:
    store = SettingsStore(db)
    prefs = await store.get()
    assert prefs.reduced_motion == "system"
    updated, changed = await store.update({"reduced_motion": "reduce"})
    assert changed == ["reduced_motion"]
    assert updated.reduced_motion == "reduce"
    assert (await store.get()).reduced_motion == "reduce"
    _, unchanged = await store.update({"reduced_motion": "reduce"})
    assert unchanged == []


async def test_settings_refuse_unknown_and_invalid(db: Database) -> None:
    store = SettingsStore(db)
    with pytest.raises(InvalidInputError):
        await store.update({"inconnu": 1})
    with pytest.raises(InvalidInputError):
        await store.update({"reduced_motion": "toujours"})


async def test_settings_survive_invalid_stored_value(db: Database) -> None:
    db.call(lambda s: s.add(Setting(key="reduced_motion", value='"ancien"', updated_at=utc_now())))
    db.call(lambda s: s.add(Setting(key="sphere_quality", value='"low"', updated_at=utc_now())))
    prefs = await SettingsStore(db).get()
    assert prefs.reduced_motion == "system"
    assert prefs.sphere_quality == "low"
