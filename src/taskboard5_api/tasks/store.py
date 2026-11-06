"""Postgres-backed task store."""

import os
import uuid
from collections.abc import Callable
from datetime import date
from typing import Any

import psycopg
import structlog
from fastapi import FastAPI, Request

from taskboard5_api.tasks.models import Task, TaskCreate

logger = structlog.get_logger(__name__)

_SCHEMA_LOCK_KEY = 5_002_001

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS tasks (
    seq        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id         UUID NOT NULL UNIQUE,
    title      TEXT NOT NULL,
    due_date   DATE NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


class StorageUnavailableError(Exception):
    """Raised when the task storage cannot be reached or does not answer in time."""


class TaskStore:
    """Task store persisting to Postgres."""

    def __init__(self, database_url: str | None) -> None:
        self._database_url = database_url
        self._schema_ready = False

    def _connect(self) -> psycopg.Connection[Any]:
        if not self._database_url:
            raise StorageUnavailableError("DATABASE_URL is not set")
        return psycopg.connect(
            self._database_url, connect_timeout=2, options="-c statement_timeout=3000"
        )

    def _run[T](self, operation: str, fn: Callable[[], T]) -> T:
        try:
            return fn()
        except StorageUnavailableError:
            raise
        except (psycopg.OperationalError, psycopg.InterfaceError) as exc:
            logger.warning(
                "task_storage_unavailable", operation=operation, error=type(exc).__name__
            )
            raise StorageUnavailableError("Task storage unavailable") from exc

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (_SCHEMA_LOCK_KEY,))
            conn.execute(_CREATE_TABLE.encode())
        self._schema_ready = True

    def ensure_schema(self) -> None:
        """Create the schema idempotently under an advisory lock."""
        self._run("ensure_schema", self._ensure_schema)

    def _ready(self) -> None:
        if not self._schema_ready:
            self._ensure_schema()

    def add(self, data: TaskCreate) -> Task:
        """Persist a new task and return it."""

        def op() -> Task:
            self._ready()
            task_id = uuid.uuid4()
            due = date.fromisoformat(data.due_date) if data.due_date else None
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO tasks (id, title, due_date) VALUES (%s, %s, %s)",
                    (task_id, data.title, due),
                )
            return Task(id=str(task_id), title=data.title, due_date=data.due_date)

        return self._run("add", op)

    def list(self) -> list[Task]:
        """Return all tasks, oldest first."""

        def op() -> list[Task]:
            self._ready()
            with self._connect() as conn:
                rows = conn.execute("SELECT id, title, due_date FROM tasks ORDER BY seq").fetchall()
            return [
                Task(
                    id=str(row[0]),
                    title=row[1],
                    due_date=row[2].isoformat() if row[2] is not None else None,
                )
                for row in rows
            ]

        return self._run("list", op)

    def ping(self) -> bool:
        """Return True if the database answers; never raises."""

        def op() -> bool:
            with self._connect() as conn:
                conn.execute("SELECT 1")
            return True

        try:
            return self._run("ping", op)
        except StorageUnavailableError:
            return False


def task_store_for(app: FastAPI) -> TaskStore:
    """Return the app's task store, creating it on first use."""
    store = getattr(app.state, "task_store", None)
    if store is None:
        url = getattr(app.state, "database_url", None) or os.environ.get("DATABASE_URL")
        store = TaskStore(url)
        app.state.task_store = store
    return store


def get_task_store(request: Request) -> TaskStore:
    """FastAPI dependency returning the app's task store."""
    return task_store_for(request.app)
