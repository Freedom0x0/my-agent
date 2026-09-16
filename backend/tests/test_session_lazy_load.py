"""Tests for /api/sessions/{id} lazy-load support."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.db import init_db, save_session_messages
from backend.app.main import create_app


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "runtime"))
    from backend.app.config import get_settings
    get_settings.cache_clear()
    app = create_app()
    return TestClient(app)


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "runtime" / "metadata.db"
    init_db(path)
    return path


def _seed_messages(db_path: Path, session_id: str, n: int) -> None:
    messages = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg-{i}"}
        for i in range(n)
    ]
    save_session_messages(db_path, session_id, messages)


def test_session_lazy_load_returns_latest_page(db_path: Path, client: TestClient) -> None:
    sid = "sess-lazy-1"
    _seed_messages(db_path, sid, 50)

    resp = client.get(f"/api/sessions/{sid}", params={"limit": 20})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_messages"] == 50
    assert body["has_more"] is True
    assert body["oldest_index"] == 30
    assert len(body["messages"]) == 20
    assert body["messages"][0]["content"] == "msg-30"
    assert body["messages"][-1]["content"] == "msg-49"


def test_session_lazy_load_before_index_returns_older_page(
    db_path: Path, client: TestClient
) -> None:
    sid = "sess-lazy-2"
    _seed_messages(db_path, sid, 60)

    resp = client.get(
        f"/api/sessions/{sid}", params={"limit": 20, "before_index": 30}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_messages"] == 30
    assert body["has_more"] is True
    assert body["oldest_index"] == 10
    assert body["messages"][0]["content"] == "msg-10"
    assert body["messages"][-1]["content"] == "msg-29"


def test_session_lazy_load_terminates_when_no_more(
    db_path: Path, client: TestClient
) -> None:
    sid = "sess-lazy-3"
    _seed_messages(db_path, sid, 5)

    resp = client.get(f"/api/sessions/{sid}", params={"limit": 20})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_messages"] == 5
    assert body["has_more"] is False
    assert body["oldest_index"] == 0
    assert len(body["messages"]) == 5


def test_session_no_limit_returns_all(db_path: Path, client: TestClient) -> None:
    sid = "sess-lazy-4"
    _seed_messages(db_path, sid, 12)

    resp = client.get(f"/api/sessions/{sid}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_messages"] == 12
    assert body["has_more"] is False
    assert body["oldest_index"] == 0
    assert len(body["messages"]) == 12


def test_session_not_found(client: TestClient) -> None:
    resp = client.get("/api/sessions/does-not-exist", params={"limit": 5})
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "session_not_found"