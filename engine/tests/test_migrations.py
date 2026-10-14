from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from ojarvis.db.base import Base
from ojarvis.db.migrate import alembic_config, current_revision, upgrade_to_head


def test_upgrade_creates_all_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "m.db"
    upgrade_to_head(db_path)
    engine = create_engine(f"sqlite:///{db_path}")
    tables = set(inspect(engine).get_table_names())
    engine.dispose()
    assert {"settings", "secret_meta", "events", "traces", "spans", "alembic_version"} <= tables
    assert current_revision(db_path) == "0001"


def test_models_and_migrations_agree(tmp_path: Path) -> None:
    """Un modèle modifié sans migration ferait échouer ce test."""
    db_path = tmp_path / "m.db"
    upgrade_to_head(db_path)
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    engine.dispose()
    assert diff == []


def test_upgrade_is_idempotent_and_reversible(tmp_path: Path) -> None:
    db_path = tmp_path / "m.db"
    upgrade_to_head(db_path)
    upgrade_to_head(db_path)
    command.downgrade(alembic_config(db_path), "base")
    assert current_revision(db_path) is None
    upgrade_to_head(db_path)
    assert current_revision(db_path) == "0001"
