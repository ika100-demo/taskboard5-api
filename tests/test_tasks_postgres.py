"""Acceptance tests for spec 002: store tasks in Postgres."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient


def create_app(database_url: str | None = None):
    from taskboard5_api.main import create_app as factory

    return factory(database_url=database_url)


UNAVAILABLE = {"detail": "Task storage unavailable"}


def _create_three(client: TestClient) -> list[dict]:
    payloads = [
        {"title": "A"},
        {"title": "  B "},
        {"title": "C", "due_date": "2020-01-01"},
    ]
    created = []
    for payload in payloads:
        response = client.post("/tasks", json=payload)
        assert response.status_code == 201
        created.append(response.json())
    return created


def test_tasks_survive_restart_in_creation_order(empty_database):  # AC-002.1
    with TestClient(create_app()) as first:
        created = _create_three(first)
    with TestClient(create_app()) as second:
        response = second.get("/tasks")
    assert response.status_code == 200
    assert response.json() == created
    assert [t["due_date"] for t in created] == [None, None, "2020-01-01"]


def test_schema_created_on_startup_and_list_empty(database_url):  # AC-002.2
    import psycopg

    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS tasks")
    with TestClient(create_app()) as client:
        response = client.get("/tasks")
    assert response.status_code == 200
    assert response.json() == []


def test_two_instances_share_tasks_in_order(empty_database):  # AC-002.3
    with TestClient(create_app()) as first, TestClient(create_app()) as second:
        created = _create_three(first)
        response = second.get("/tasks")
    assert response.status_code == 200
    assert response.json() == created


def test_create_during_outage_is_503_and_not_stored(empty_database, db_outage):  # AC-002.4
    with TestClient(create_app(database_url=db_outage.url)) as client:
        db_outage.cut()
        started = time.monotonic()
        response = client.post("/tasks", json={"title": "lost"})
        elapsed = time.monotonic() - started
        assert response.status_code == 503
        assert response.json() == UNAVAILABLE
        assert response.headers["content-type"].startswith("application/json")
        assert elapsed < 5
        db_outage.restore()
        listed = client.get("/tasks")
    assert listed.status_code == 200
    assert all(t["title"] != "lost" for t in listed.json())


def test_list_during_outage_is_503(empty_database, db_outage):  # AC-002.5
    with TestClient(create_app(database_url=db_outage.url)) as client:
        db_outage.cut()
        started = time.monotonic()
        response = client.get("/tasks")
        elapsed = time.monotonic() - started
    assert response.status_code == 503
    assert response.json() == UNAVAILABLE
    assert elapsed < 5


def test_ready_follows_database_health_stays_ok(empty_database, db_outage):  # AC-002.6
    with TestClient(create_app(database_url=db_outage.url)) as client:
        assert client.get("/ready").status_code == 200
        db_outage.cut()
        not_ready = client.get("/ready")
        assert not_ready.status_code == 503
        assert not_ready.json() == {"status": "not ready"}
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}
        db_outage.restore()
        ready = client.get("/ready")
        assert ready.status_code == 200
        assert ready.json() == {"status": "ready"}
