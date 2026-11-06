"""Smoke tests for spec 001 (AC-001.1, AC-001.5): reach the service only via SMOKE_BASE_URL."""

from __future__ import annotations

import json
import urllib.request
import uuid

import pytest


def _request(url: str, payload: dict | None = None) -> tuple[int, object]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(  # noqa: S310
        url, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=10) as response:  # noqa: S310
        return response.status, json.load(response)


@pytest.mark.smoke
@pytest.mark.writes
def test_smoke_ac_001_1_create_task(smoke_base_url: str) -> None:  # AC-001.1
    title = f"smoke-{uuid.uuid4()}"
    status, body = _request(smoke_base_url + "/tasks", {"title": title})
    assert status == 201
    assert body["title"] == title
    assert body["due_date"] is None
    uuid.UUID(body["id"])


@pytest.mark.smoke
@pytest.mark.writes
def test_smoke_ac_001_5_list_in_creation_order(smoke_base_url: str) -> None:  # AC-001.5
    created = []
    for _ in range(3):
        _, body = _request(smoke_base_url + "/tasks", {"title": f"smoke-{uuid.uuid4()}"})
        created.append(body)
    status, listed = _request(smoke_base_url + "/tasks")
    assert status == 200
    ids = [t["id"] for t in created]
    assert [t for t in listed if t["id"] in ids] == created


@pytest.mark.smoke
def test_smoke_ac_001_5_list_is_readable(smoke_base_url: str) -> None:  # AC-001.5
    status, listed = _request(smoke_base_url + "/tasks")
    assert status == 200
    assert isinstance(listed, list)
