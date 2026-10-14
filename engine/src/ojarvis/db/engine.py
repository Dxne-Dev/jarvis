"""Accès SQLite : mode WAL, clés étrangères actives, sessions courtes.

Le code asynchrone passe par `Database.run`, qui exécute la fonction dans un thread :
la boucle d'événements n'est jamais bloquée par la base (leçon de l'ancien Jarvis).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import anyio.to_thread
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def _on_connect(dbapi_connection: Any, _: Any) -> None:
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.engine: Engine = create_engine(
            f"sqlite:///{path}",
            connect_args={"check_same_thread": False, "timeout": 10},
        )
        event.listen(self.engine, "connect", _on_connect)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self._sessions()
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    def call[T](self, fn: Callable[[Session], T]) -> T:
        with self.session() as session:
            return fn(session)

    async def run[T](self, fn: Callable[[Session], T]) -> T:
        return await anyio.to_thread.run_sync(self.call, fn)

    def dispose(self) -> None:
        self.engine.dispose()
