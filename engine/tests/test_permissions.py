"""Niveaux de permission : une seule porte, validation, double confirmation, journal, plans."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from ojarvis.agent.executor import PlanExecutor, fill_placeholders
from ojarvis.agent.plans import PlanIn, PlanStore, StepIn
from ojarvis.audit.journal import AuditJournal
from ojarvis.core.errors import ConflictError, InvalidInputError
from ojarvis.db.engine import Database
from ojarvis.db.migrate import upgrade_to_head
from ojarvis.events.bus import EventBus
from ojarvis.permissions.gate import Approval, ApprovalRequiredError, PermissionGate
from ojarvis.tools.base import ToolContext, ToolRegistry, UnknownToolError
from tests.fake_tools import Act, Destroy, Echo, install


@pytest.fixture
def db(tmp_path: Path) -> Database:
    path = tmp_path / "agent.db"
    upgrade_to_head(path)
    return Database(path)


@pytest.fixture
def setup(db: Database, tmp_path: Path) -> tuple[PermissionGate, AuditJournal, Echo, Act, Destroy]:
    registry = ToolRegistry()
    echo, act, destroy = install(registry)
    journal = AuditJournal(db)

    def context() -> ToolContext:
        return ToolContext(http=cast(httpx.AsyncClient, None), secret=lambda _: None, home=tmp_path)

    return PermissionGate(registry, journal, context), journal, echo, act, destroy


async def actions(journal: AuditJournal) -> list[str]:
    records, _ = await journal.recent()
    return [r.action for r in reversed(records)]


async def test_reading_runs_alone_and_leaves_no_journal_entry(setup: Any) -> None:
    gate, journal, echo, _, _ = setup
    output = await gate.execute("echo", {"texte": "salut"})
    assert output.text == "écho : salut"
    assert echo.calls == ["salut"]
    assert await actions(journal) == []


async def test_acting_needs_an_approval_and_is_journaled(setup: Any) -> None:
    gate, journal, _, act, _ = setup
    with pytest.raises(ApprovalRequiredError):
        await gate.execute("agir", {"cible": "formulaire"})
    assert act.calls == []
    await gate.execute("agir", {"cible": "formulaire"}, approval=Approval("p1", 1, level=2))
    assert act.calls == [("formulaire", "")]
    assert await actions(journal) == ["outil.agir", "outil.agir.fait"]
    assert (await journal.verify()).ok


async def test_destroying_needs_a_double_confirmation(setup: Any) -> None:
    gate, _, _, _, destroy = setup
    with pytest.raises(ApprovalRequiredError, match="double confirmation"):
        await gate.execute("detruire", {"chemin": "a.txt"}, approval=Approval("p", 1, level=3))
    await gate.execute(
        "detruire", {"chemin": "a.txt"}, approval=Approval("p", 1, level=3, double_confirmed=True)
    )
    assert destroy.calls == ["a.txt"]


async def test_a_step_cannot_climb_above_the_level_you_approved(setup: Any) -> None:
    gate, _, _, act, _ = setup
    approval = Approval("p", 1, level=2, double_confirmed=True)
    with pytest.raises(ApprovalRequiredError, match="plus élevé"):
        await gate.execute("agir", {"cible": "danger-zone"}, approval=approval)
    assert act.calls == []


async def test_unknown_tools_and_extra_arguments_are_refused(setup: Any) -> None:
    gate, _, _, _, _ = setup
    with pytest.raises(UnknownToolError):
        await gate.execute("formater_disque", {})
    with pytest.raises(InvalidInputError):
        await gate.execute("echo", {"texte": "x", "admin": True})


async def test_a_failed_action_is_journaled_too(setup: Any) -> None:
    gate, journal, _, act, _ = setup

    async def broken(args: Any, ctx: Any) -> Any:
        raise RuntimeError("boum")

    act.run = broken
    with pytest.raises(RuntimeError):
        await gate.execute("agir", {"cible": "x"}, approval=Approval("p", 1, level=2))
    assert await actions(journal) == ["outil.agir", "outil.agir.echec"]


# ---------------------------------------------------------------------- plans


async def test_plans_are_checked_before_being_shown(setup: Any, db: Database) -> None:
    gate, _, _, _, _ = setup
    store = PlanStore(db, gate)

    def plan(*steps: StepIn) -> PlanIn:
        return PlanIn(titre="Plan de test", etapes=list(steps))

    with pytest.raises(UnknownToolError):
        await store.create(
            plan(StepIn(outil="inconnu", arguments={}, pourquoi="x")),
            conversation_id=None,
            request="r",
            tainted=False,
        )
    with pytest.raises(InvalidInputError):
        await store.create(
            plan(StepIn(outil="echo", arguments={"texte": "a", "b": 1}, pourquoi="x")),
            conversation_id=None,
            request="r",
            tainted=False,
        )
    with pytest.raises(InvalidInputError, match="précédente"):
        await store.create(
            plan(StepIn(outil="echo", arguments={"texte": "{{etape 2}}"}, pourquoi="x")),
            conversation_id=None,
            request="r",
            tainted=False,
        )
    # La cible d'une action doit être connue au moment de la validation.
    with pytest.raises(InvalidInputError, match="connu avant la validation"):
        await store.create(
            plan(
                StepIn(outil="echo", arguments={"texte": "a"}, pourquoi="x"),
                StepIn(outil="agir", arguments={"cible": "{{etape 1}}"}, pourquoi="y"),
            ),
            conversation_id=None,
            request="r",
            tainted=False,
        )
    record = await store.create(
        plan(
            StepIn(outil="echo", arguments={"texte": "a"}, pourquoi="lire"),
            StepIn(
                outil="agir", arguments={"cible": "fiche", "contenu": "{{ etape 1 }}"}, pourquoi="y"
            ),
        ),
        conversation_id=None,
        request="r",
        tainted=True,
    )
    assert record.status == "proposed"
    assert record.max_level == 2
    assert record.tainted
    assert [s.level for s in record.steps] == [1, 2]
    assert record.steps[1].description == "Agir sur fiche"


def test_placeholders_take_the_previous_results() -> None:
    filled = fill_placeholders(
        {"contenu": "Résumé : {{etape 1}} / {{ etape 2 }}", "liste": ["{{etape 1}}"], "n": 3},
        {1: "un", 2: "deux"},
    )
    assert filled == {"contenu": "Résumé : un / deux", "liste": ["un"], "n": 3}


async def test_interrupted_plans_are_never_replayed(setup: Any, db: Database) -> None:
    gate, journal, _, act, _ = setup
    store = PlanStore(db, gate)
    record = await store.create(
        PlanIn(
            titre="Plan coupé",
            etapes=[
                StepIn(outil="agir", arguments={"cible": "a"}, pourquoi="x"),
                StepIn(outil="agir", arguments={"cible": "b"}, pourquoi="y"),
            ],
        ),
        conversation_id=None,
        request="r",
        tainted=False,
    )
    await store.set_status(record.id, "running")
    await store.set_step(record.id, 1, status="running")
    executor = PlanExecutor(
        plans=store,
        gate=gate,
        journal=journal,
        router=cast(Any, None),
        conversations=cast(Any, None),
        bus=EventBus(),
    )
    assert await executor.recover() == 1
    after = await store.get(record.id)
    assert after.status == "failed"
    assert [s.status for s in after.steps] == ["failed", "skipped"]
    assert act.calls == []
    assert "plan.interrompu" in await actions(journal)


async def test_stop_lets_the_running_step_finish_and_launches_no_other(
    setup: Any, db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate, journal, _, act, _ = setup
    store = PlanStore(db, gate)
    record = await store.create(
        PlanIn(
            titre="Commander le thé",
            etapes=[
                StepIn(outil="agir", arguments={"cible": "panier"}, pourquoi="x"),
                StepIn(outil="agir", arguments={"cible": "paiement"}, pourquoi="y"),
                StepIn(outil="agir", arguments={"cible": "confirmation"}, pourquoi="z"),
            ],
        ),
        conversation_id=None,
        request="r",
        tainted=False,
    )
    executor = PlanExecutor(
        plans=store,
        gate=gate,
        journal=journal,
        router=cast(Any, None),
        conversations=cast(Any, None),
        bus=EventBus(),
    )
    sections: list[list[str]] = []

    async def synthesize(_plan: Any, parts: list[str]) -> str:
        sections.append(parts)
        return "Arrêté après le panier."

    monkeypatch.setattr(executor, "_synthesize", synthesize)
    started, release = asyncio.Event(), asyncio.Event()
    run = act.run

    async def slow(args: Any, ctx: Any) -> Any:
        started.set()
        await release.wait()
        return await run(args, ctx)

    monkeypatch.setattr(act, "run", slow)
    with pytest.raises(ConflictError):
        await executor.stop(record.id)  # pas encore lancé : rien à arrêter
    await executor.approve(record.id)
    await started.wait()
    await executor.stop(record.id)
    release.set()
    await executor._running[record.id]
    after = await store.get(record.id)
    assert after.status == "stopped"
    assert [s.status for s in after.steps] == ["done", "skipped", "skipped"]
    assert act.calls == [("panier", "")]  # l'étape en cours a fini, aucune autre n'est partie
    assert "Arrêté par l'utilisateur avant l'étape 2." in sections[0]
    assert "plan.arrete" in await actions(journal)
    with pytest.raises(ConflictError):
        await executor.stop(record.id)  # fini : plus rien à arrêter
