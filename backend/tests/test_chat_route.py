"""Tests for the POST /api/chat route."""
from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from backend.app.config import get_settings
from backend.app.db import FileRecord, init_db, insert_file
from backend.app.main import create_app
from backend.app.mcp import agent as agent_module
from backend.app.mcp.session import reset_session_store


@pytest.fixture()
def app_with_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("MODEL_BASE_URL", "https://example.test")
    monkeypatch.setenv("MODEL_API_KEY", "fake-key")
    monkeypatch.setenv("MODEL_NAME", "fake-model")
    get_settings.cache_clear()
    reset_session_store()
    app = create_app()
    init_db((tmp_path / "runtime" / "metadata.db"))
    return app, tmp_path


@pytest.fixture()
def client(app_with_data_dir) -> TestClient:
    app, _ = app_with_data_dir
    return TestClient(app)


@pytest.fixture()
def sample_file(tmp_path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "明细"
    ws.append(["部门", "订单号", "金额"])
    ws.append(["研发", "A001", "1,200"])
    ws.append(["销售", "A002", "800"])
    out = tmp_path / "sample.xlsx"
    wb.save(out)
    return out


def _upload_file(client: TestClient, path: Path) -> str:
    with path.open("rb") as fh:
        resp = client.post(
            "/api/files",
            files={"file": ("sample.xlsx", fh, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
    assert resp.status_code == 201
    return resp.json()["file_id"]


def _register_in_db(tmp_path: Path, file_id: str, path: Path) -> None:
    record = FileRecord(
        file_id=file_id,
        original_name="sample.xlsx",
        stored_path=str(path),
        file_type="xlsx",
        size_bytes=path.stat().st_size,
        sha256="x",
        inspection={"filename": "sample.xlsx", "file_type": "xlsx", "sheets": []},
        created_at=_dt.datetime.utcnow().isoformat(),
    )
    insert_file(tmp_path / "runtime" / "metadata.db", record)


def test_chat_route_returns_reply(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(
        agent_module, "_default_chat_caller",
        lambda **kwargs: {"stop_reason": "end_turn", "content": [{"type": "text", "text": "你好"}]},
    )
    response = client.post(
        "/api/chat",
        json={"message": "hi", "file_ids": [], "session_id": "s1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "你好"
    assert body["error_code"] is None
    assert body["session_id"] == "s1"


def test_chat_route_validates_empty_message(client: TestClient) -> None:
    response = client.post("/api/chat", json={"message": "  ", "file_ids": [], "session_id": "x"})
    assert response.status_code == 200
    body = response.json()
    assert body["error_code"] == "invalid_request"


def test_chat_route_validates_too_long_message(client: TestClient) -> None:
    response = client.post("/api/chat", json={"message": "x" * 4001, "file_ids": [], "session_id": "x"})
    body = response.json()
    assert body["error_code"] == "invalid_request"


def test_chat_route_returns_session_id_when_missing(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(
        agent_module, "_default_chat_caller",
        lambda **kwargs: {"stop_reason": "end_turn", "content": [{"type": "text", "text": "ok"}]},
    )
    response = client.post("/api/chat", json={"message": "hi", "file_ids": []})
    assert response.status_code == 200
    body = response.json()
    assert body.get("session_id")


def test_chat_route_full_flow_with_tool_calls(
    app_with_data_dir, client: TestClient, sample_file: Path, monkeypatch
) -> None:
    _, tmp_path = app_with_data_dir
    file_id = _upload_file(client, sample_file)

    # Plan: first response asks tablex_upload, second returns text reply.
    from backend.app.mcp.tools import TABLEX_TOOL_DEFINITIONS
    from backend.app.mcp.session import get_session_store

    store = get_session_store()
    # pre-register file in session so handler finds it
    sess = store.get_or_create("flow")
    sess.files[file_id] = {
        "path": str(sample_file),
        "sha256": "x",
        "original_name": "sample.xlsx",
    }

    responses = [
        {
            "stop_reason": "tool_use",
            "content": [
                {"type": "tool_use", "id": "tu-1", "name": "tablex_upload", "input": {"file_id": file_id}},
            ],
        },
        {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "文件已加载"}],
        },
    ]

    monkeypatch.setattr(agent_module, "_default_chat_caller", lambda **kwargs: responses.pop(0))

    response = client.post(
        "/api/chat",
        json={"message": "加载并检查", "file_ids": [file_id], "session_id": "flow"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "文件已加载"
    assert any(tc["tool"] == "tablex_upload" for tc in body["tool_calls"])
    # Tables should now be in session
    assert any(k.startswith(file_id) for k in sess.tables.keys())


def test_chat_route_handles_chat_error(
    app_with_data_dir, client: TestClient, sample_file: Path, monkeypatch
) -> None:
    _, tmp_path = app_with_data_dir
    file_id = _upload_file(client, sample_file)
    monkeypatch.setattr(
        agent_module, "_default_chat_caller",
        lambda **kwargs: {"stop_reason": "end_turn", "content": []} or (_ for _ in ()).throw(
            agent_module.ChatError("model_timeout", "网络超时"),
        ),
    )

    # Actually force an error via a callable that raises.
    def boom(**kwargs):
        raise agent_module.ChatError("model_timeout", "网络超时")

    monkeypatch.setattr(agent_module, "_default_chat_caller", boom)
    response = client.post(
        "/api/chat",
        json={"message": "hi", "file_ids": [file_id], "session_id": "err"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["error_code"] == "model_timeout"
    assert "网络超时" in body["reply"]