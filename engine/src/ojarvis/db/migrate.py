"""Migrations Alembic lancées une seule fois, au démarrage du moteur."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def alembic_config(db_path: Path) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return config


def upgrade_to_head(db_path: Path) -> None:
    command.upgrade(alembic_config(db_path), "head")


def current_revision(db_path: Path) -> str | None:
    from alembic.runtime.migration import MigrationContext  # noqa: PLC0415
    from sqlalchemy import create_engine  # noqa: PLC0415

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()
