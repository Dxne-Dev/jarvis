"""Workflows persistés et planificateur : reprise après arrêt, rattrapage, événements."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest

from ojarvis.automations.models import EventTrigger, Instruction, Reminder, TimeTrigger
from ojarvis.automations.schedule import Daily, Once
from ojarvis.automations.scheduler import AutomationScheduler, steps_for
from ojarvis.automations.store import AutomationStore
from ojarvis.core.context import correlation_id_var
from ojarvis.db.engine import Database
from ojarvis.db.migrate import upgrade_to_head
from ojarvis.events.bus import Event, EventBus
from ojarvis.workflows.engine import RunRecord, WorkflowEngine

PARIS = ZoneInfo("Europe/Paris")


@pytest.fixture
def db(tmp_path: Path) -> Database:
    path = tmp_path / "wf.db"
    upgrade_to_head(path)
    return Database(path)


class Steps:
    """Étapes de test : elles notent leurs passages ; l'une peut bloquer ou échouer."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.block = asyncio.Event()
        self.blocking = False
        self.failures = 0

    async def first(self, step: dict[str, Any], run: RunRecord) -> dict[str, Any]:
        self.calls.append("premiere")
        return {"valeur": step.get("valeur", 1)}

    async def second(self, step: dict[str, Any], run: RunRecord) -> dict[str, Any]:
        self.calls.append(f"seconde:{run.context.get('valeur')}")
        if self.blocking:
            await self.block.wait()
        if self.failures > 0:
            self.failures -= 1
            raise RuntimeError("panne passagère")
        return {"fini": True}

    def handlers(self) -> dict[str, Any]:
        return {"premiere": self.first, "seconde": self.second}


async def wait_status(engine: WorkflowEngine, run_id: str, status: str) -> RunRecord:
    for _ in range(200):
        record = await engine.get(run_id)
        if record.status == status:
            return record
        await asyncio.sleep(0.01)
    raise AssertionError(f"toujours {record.status}")


async def test_steps_run_in_order_and_share_their_results(db: Database) -> None:
    steps = Steps()
    engine = WorkflowEngine(db, EventBus(), steps.handlers())
    await engine.start()
    run = await engine.submit(
        kind="test",
        title="Deux étapes",
        steps=[{"type": "premiere", "valeur": 7}, {"type": "seconde"}],
    )
    done = await wait_status(engine, run.id, "done")
    assert steps.calls == ["premiere", "seconde:7"]
    assert done.context == {"valeur": 7, "fini": True}
    assert done.position == 2
    await engine.close()


async def test_a_run_cut_by_a_crash_resumes_at_the_interrupted_step(db: Database) -> None:
    steps = Steps()
    steps.blocking = True
    engine = WorkflowEngine(db, EventBus(), steps.handlers())
    await engine.start()
    run = await engine.submit(
        kind="test", title="Coupé", steps=[{"type": "premiere"}, {"type": "seconde"}]
    )
    for _ in range(200):
        if steps.calls == ["premiere", "seconde:1"]:
            break
        await asyncio.sleep(0.01)
    await engine.close()  # arrêt brutal pendant la seconde étape
    cut = await engine.get(run.id)
    assert cut.status == "running"
    assert cut.position == 1  # la première étape est enregistrée comme faite

    # Redémarrage : un nouveau moteur reprend à la seconde étape, sans refaire la première.
    steps.blocking = False
    restarted = WorkflowEngine(db, EventBus(), steps.handlers())
    assert await restarted.start() == 1
    done = await wait_status(restarted, run.id, "done")
    assert steps.calls == ["premiere", "seconde:1", "seconde:1"]
    assert done.context["fini"] is True
    await restarted.close()


async def test_a_failing_step_is_retried_then_given_up(db: Database) -> None:
    steps = Steps()
    steps.failures = 1
    bus = EventBus()
    finished: list[Event] = []

    async def collect(event: Event) -> None:
        finished.append(event)

    bus.subscribe("workflow.finished", collect)
    engine = WorkflowEngine(db, bus, steps.handlers(), retry_delay_s=0.05)
    await engine.start()
    run = await engine.submit(kind="test", title="Panne", steps=[{"type": "seconde"}])
    assert (await wait_status(engine, run.id, "done")).attempts == 1

    steps.failures = 5
    broken = await engine.submit(kind="test", title="Panne durable", steps=[{"type": "seconde"}])
    failed = await wait_status(engine, broken.id, "failed")
    assert failed.attempts == 3
    assert "panne passagère" in (failed.error or "")
    await asyncio.sleep(0.05)
    assert [e.payload["status"] for e in finished] == ["done", "failed"]
    await engine.close()


async def test_unknown_steps_are_refused(db: Database) -> None:
    engine = WorkflowEngine(db, EventBus(), Steps().handlers())
    with pytest.raises(ValueError, match="inconnues"):
        await engine.submit(kind="test", title="x", steps=[{"type": "formater"}])


# ---------------------------------------------------------------------- planificateur


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class FakeWorkflows:
    def __init__(self) -> None:
        self.submitted: list[dict[str, Any]] = []

    async def submit(self, **kwargs: Any) -> RunRecord:
        self.submitted.append(kwargs)
        now = datetime.now(UTC)
        return RunRecord(
            "run",
            "automation",
            kwargs.get("automation_id"),
            kwargs["title"],
            "pending",
            kwargs["steps"],
            0,
            kwargs.get("context", {}),
            0,
            None,
            now,
            now,
            None,
            None,
        )


@pytest.fixture
def clock() -> Clock:
    return Clock(datetime(2026, 10, 15, 5, 0, tzinfo=UTC))


@pytest.fixture
def store(db: Database, clock: Clock) -> AutomationStore:
    return AutomationStore(db, lambda: PARIS, clock=clock)


async def test_due_automations_fire_and_get_their_next_time(
    store: AutomationStore, clock: Clock
) -> None:
    workflows = FakeWorkflows()
    scheduler = AutomationScheduler(
        store=store, workflows=cast(Any, workflows), bus=EventBus(), clock=clock
    )
    daily = await store.create(
        "Café",
        TimeTrigger(quand=Daily(heure="08:00")),
        Reminder(texte="Café !"),
        created_by="utilisateur",
    )
    # Créée le 15/10 à 7 h (Paris) : prochaine fois le jour même à 8 h.
    assert daily.next_run_at == datetime(2026, 10, 15, 6, 0, tzinfo=UTC)
    assert await scheduler.tick() == []

    clock.now = datetime(2026, 10, 15, 6, 0, 5, tzinfo=UTC)
    assert await scheduler.tick() == [daily.id]
    assert workflows.submitted[0]["steps"] == [
        {"type": "notifier", "titre": "Café", "texte": "Café !"}
    ]
    after = await store.get(daily.id)
    assert after.run_count == 1
    assert after.next_run_at == datetime(2026, 10, 16, 6, 0, tzinfo=UTC)
    assert after.last_status == "running"


async def test_a_one_shot_turns_itself_off(store: AutomationStore, clock: Clock) -> None:
    scheduler = AutomationScheduler(
        store=store, workflows=cast(Any, FakeWorkflows()), bus=EventBus(), clock=clock
    )
    once = await store.create(
        "Appeler maman",
        TimeTrigger(quand=Once(le="2026-10-16T09:00")),
        Reminder(texte="Appeler maman"),
        created_by="jarvis",
    )
    assert once.one_shot
    clock.now = datetime(2026, 10, 16, 7, 0, 30, tzinfo=UTC)
    assert await scheduler.tick() == [once.id]
    after = await store.get(once.id)
    assert not after.enabled
    assert after.next_run_at is None


async def test_missed_runs_are_caught_up_or_skipped(store: AutomationStore, clock: Clock) -> None:
    workflows = FakeWorkflows()
    clock.now = datetime(2026, 10, 15, 4, 0, tzinfo=UTC)
    scheduler = AutomationScheduler(
        store=store, workflows=cast(Any, workflows), bus=EventBus(), clock=clock
    )
    soon = await store.create(
        "Récent",
        TimeTrigger(quand=Daily(heure="08:00")),
        Reminder(texte="a"),
        created_by="utilisateur",
    )
    # PC éteint : rallumé 2 h après l'échéance → rattrapée.
    clock.now = datetime(2026, 10, 15, 8, 0, tzinfo=UTC)
    assert await scheduler.tick() == [soon.id]
    # Éteint toute une journée : l'échéance du 16 est manquée de plus de 6 h → notée, pas lancée.
    clock.now = datetime(2026, 10, 17, 4, 0, tzinfo=UTC)
    assert await scheduler.tick() == []
    after = await store.get(soon.id)
    assert after.last_status == "missed"
    assert after.run_count == 1
    assert after.next_run_at == datetime(2026, 10, 17, 6, 0, tzinfo=UTC)


async def test_events_trigger_automations_without_chain_reactions(
    store: AutomationStore, clock: Clock
) -> None:
    workflows = FakeWorkflows()
    bus = EventBus()
    scheduler = AutomationScheduler(
        store=store, workflows=cast(Any, workflows), bus=bus, clock=clock
    )
    watcher = await store.create(
        "Plan en échec",
        EventTrigger(evenement="plan.finished", filtre={"status": "failed"}),
        Instruction(texte="Explique-moi pourquoi le plan a échoué."),
        created_by="utilisateur",
    )
    await scheduler.start()
    await bus.publish("plan.finished", {"id": "p1", "status": "done"})
    await bus.publish("plan.finished", {"id": "p2", "status": "failed"})
    await bus.drain()
    assert len(workflows.submitted) == 1
    assert workflows.submitted[0]["context"]["evenement"] == {
        "type": "plan.finished",
        "id": "p2",
        "status": "failed",
    }
    assert steps_for(await store.get(watcher.id))[0]["type"] == "consigne"

    # Une minute au plus une fois ; et rien de ce que font les automatisations ne relance.
    await bus.publish("plan.finished", {"id": "p3", "status": "failed"})
    await bus.drain()
    clock.now += timedelta(minutes=2)
    token = correlation_id_var.set("wf1234")
    try:
        await bus.publish("plan.finished", {"id": "p4", "status": "failed"})
    finally:
        correlation_id_var.reset(token)
    await bus.drain()
    assert len(workflows.submitted) == 1
    await bus.publish("plan.finished", {"id": "p5", "status": "failed"})
    await bus.drain()
    assert len(workflows.submitted) == 2
    await scheduler.close()
