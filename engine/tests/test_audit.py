"""Journal des actions : ajout seul, chaîne d'empreintes, falsification détectée."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from ojarvis.audit.journal import GENESIS, AuditJournal
from ojarvis.db.engine import Database
from ojarvis.db.migrate import upgrade_to_head
from ojarvis.events.bus import EventBus
from ojarvis.security.redaction import REDACTOR


@pytest.fixture
def db(tmp_path: Path) -> Database:
    path = tmp_path / "journal.db"
    upgrade_to_head(path)
    return Database(path)


async def test_entries_are_chained_and_verified(db: Database) -> None:
    journal = AuditJournal(db)
    first = await journal.append(
        actor="utilisateur", action="plan.approuve", level=2, summary="Plan validé"
    )
    second = await journal.append(
        actor="jarvis",
        action="outil.execute",
        level=2,
        summary="Formulaire rempli",
        details={"champ": "prix", "valeur": "42 €"},
    )
    assert first.prev_hash == GENESIS
    assert second.prev_hash == first.hash
    report = await journal.verify()
    assert report.ok
    assert report.count == 2
    records, total = await journal.recent()
    assert total == 2
    assert [r.action for r in records] == ["outil.execute", "plan.approuve"]


async def test_the_database_refuses_changes_and_deletions(db: Database) -> None:
    journal = AuditJournal(db)
    await journal.append(actor="jarvis", action="outil.execute", level=2, summary="Action")
    with db.engine.begin() as connection, pytest.raises(DatabaseError, match="immuable"):
        connection.execute(text("UPDATE audit_log SET summary = 'autre chose'"))
    with db.engine.begin() as connection, pytest.raises(DatabaseError, match="immuable"):
        connection.execute(text("DELETE FROM audit_log"))


async def test_tampering_behind_the_triggers_is_detected(db: Database) -> None:
    bus = EventBus()
    journal = AuditJournal(db, bus)
    for i in range(3):
        await journal.append(actor="jarvis", action="outil.execute", level=2, summary=f"Action {i}")
    # Quelqu'un retire les déclencheurs et réécrit l'histoire…
    with db.engine.begin() as connection:
        connection.execute(text("DROP TRIGGER audit_log_no_update"))
        connection.execute(text("UPDATE audit_log SET summary = 'Rien de grave' WHERE id = 2"))
    async with bus.stream("audit.*") as events:
        report = await journal.verify()
        alert = events.get_nowait()
    assert not report.ok
    assert report.broken_at == 2
    assert alert.type == "audit.integrity_failed"


async def test_secrets_never_enter_the_journal(db: Database) -> None:
    REDACTOR.add_value("jeton-tres-secret-123")
    journal = AuditJournal(db)
    record = await journal.append(
        actor="jarvis",
        action="outil.execute",
        level=2,
        summary="Envoi avec jeton-tres-secret-123",
        details={"entete": "Bearer jeton-tres-secret-123"},
    )
    assert "jeton-tres-secret-123" not in record.summary
    assert "jeton-tres-secret-123" not in str(record.details)
    assert (await journal.verify()).ok
