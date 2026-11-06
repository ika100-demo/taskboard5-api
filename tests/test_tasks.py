"""Acceptance tests for spec 001: create and list tasks, run against Postgres."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from taskboard5_api.main import create_app


@pytest.fixture()
def tasks_client(empty_database) -> Iterator[TestClient]:
    """A client whose app uses an empty Postgres tasks table."""
    with TestClient(create_app()) as test_client:
        yield test_client


def _assert_loc(response, field: str) -> None:
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list)
    assert any(entry["loc"] == ["body", field] for entry in detail)


def test_create_task_returns_201_with_id_title_and_null_due_date(tasks_client):  # AC-001.1
    response = tasks_client.post("/tasks", json={"title": "Buy milk"})
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "title", "due_date"}
    assert str(uuid.UUID(body["id"])) == body["id"]
    assert body["title"] == "Buy milk"
    assert body["due_date"] is None


@pytest.mark.parametrize("due", ["2026-12-01", "2020-01-01"])
def test_create_task_echoes_due_date_including_past(tasks_client, due):  # AC-001.2
    response = tasks_client.post("/tasks", json={"title": "File taxes", "due_date": due})
    assert response.status_code == 201
    assert response.json()["due_date"] == due


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"title": 5},
        {"title": True},
        {"title": {}},
        {"title": []},
        {"title": None},
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 201},
    ],
)
def test_invalid_title_is_422_and_nothing_stored(tasks_client, payload):  # AC-001.3
    _assert_loc(tasks_client.post("/tasks", json=payload), "title")
    assert tasks_client.get("/tasks").json() == []


@pytest.mark.parametrize(
    "due", ["tomorrow", "2026-13-01", "2026-02-30", "2026-12-01T10:00:00", 20261201]
)
def test_invalid_due_date_is_422_and_nothing_stored(tasks_client, due):  # AC-001.4
    response = tasks_client.post("/tasks", json={"title": "ok", "due_date": due})
    _assert_loc(response, "due_date")
    assert tasks_client.get("/tasks").json() == []


def test_list_returns_tasks_in_creation_order(tasks_client):  # AC-001.5
    created = [tasks_client.post("/tasks", json={"title": name}).json() for name in ("A", "B", "C")]
    response = tasks_client.get("/tasks")
    assert response.status_code == 200
    assert response.json() == created


def test_list_is_empty_initially(tasks_client):  # AC-001.6
    response = tasks_client.get("/tasks")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize("title", ["  Buy milk ", "y" * 200])
def test_title_is_stored_without_trimming(tasks_client, title):  # AC-001.8
    response = tasks_client.post("/tasks", json={"title": title})
    assert response.status_code == 201
    assert response.json()["title"] == title
    assert [t["title"] for t in tasks_client.get("/tasks").json()] == [title]
