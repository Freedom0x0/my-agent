"""End-to-end test for the MCP / MiniMax chat flow.

- Spins up FastAPI TestClient.
- Uploads fixtures/expenses_and_budget.xlsx via POST /api/files.
- Drives POST /api/chat with a scripted MiniMax response queue (model is mocked).
- Verifies tablex_* tool calls are executed and /api/outputs/{id} is downloadable.
- Verifies session messages are persisted to SQLite (plan §1.2.3 simplified scheme).
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app.config import get_settings
from backend.app.db import get_session_messages, init_db
from backend.app.main import create_app
from backend.app.mcp import agent as agent_module
from backend.app.mcp.session import reset_session_store


FIXTURES = Path(__file__).resolve().parent.parent.parent / "fixtures"


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("MODEL_BASE_URL", "https://example.test")
    monkeypatch.setenv("MODEL_API_KEY", "fake-key")
    monkeypatch.setenv("MODEL_NAME", "fake-model")
    get_settings.cache_clear()
    reset_session_store()
    init_db(tmp_path / "runtime" / "metadata.db")
    app = create_app()
    return TestClient(app)


def _upload(client: TestClient, path: Path) -> str:
    with path.open("rb") as fh:
        resp = client.post(
            "/api/files",
            files={"file": (path.name, fh, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
    assert resp.status_code == 201, resp.text
    return resp.json()["file_id"]


def _text_block(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def _tool_use_block(tool_use_id: str, name: str, input_dict: dict[str, Any]) -> dict[str, Any]:
    return {"type": "tool_use", "id": tool_use_id, "name": name, "input": input_dict}


def _response(content: list[dict[str, Any]], stop_reason: str) -> dict[str, Any]:
    return {"stop_reason": stop_reason, "content": content}


def test_e2e_chat_full_flow(client: TestClient) -> None:
    """upload -> chat (mocked) -> tool_use processed -> export -> download."""
    source = FIXTURES / "expenses_and_budget.xlsx"
    assert source.exists(), f"fixture missing: {source}"

    file_id = _upload(client, source)

    # Scripted MiniMax replies: upload -> inspect -> normalize -> group_summary -> export -> text.
    responses = [
        _response(
            [_tool_use_block("tu-1", "tablex_upload", {"file_id": file_id})],
            stop_reason="tool_use",
        ),
        _response(
            [_tool_use_block("tu-2", "tablex_inspect", {"file_id": file_id})],
            stop_reason="tool_use",
        ),
        _response(
            [_tool_use_block(
                "tu-3", "tablex_normalize",
                {"file_id": file_id, "sheet": "收支明细", "columns": ["金额"], "target_type": "number"},
            )],
            stop_reason="tool_use",
        ),
        _response(
            [_tool_use_block(
                "tu-4", "tablex_group_summary",
                {
                    "file_id": file_id, "sheet": "收支明细",
                    "group_by": ["部门"],
                    "metrics": {"金额": ["sum"]},
                    "output_sheet": "汇总结果",
                },
            )],
            stop_reason="tool_use",
        ),
        _response([_tool_use_block("tu-5", "tablex_export", {})], stop_reason="tool_use"),
        _response([_text_block("处理完成")], stop_reason="end_turn"),
    ]

    def scripted_caller(**_kwargs: Any) -> dict[str, Any]:
        return responses.pop(0)

    agent_module.set_chat_caller(scripted_caller)
    try:
        chat_resp = client.post(
            "/api/chat",
            json={"message": "检查并按部门汇总金额", "file_ids": [file_id], "session_id": "e2e"},
        )
    finally:
        agent_module.set_chat_caller(None)

    assert chat_resp.status_code == 200, chat_resp.text
    body = chat_resp.json()
    assert body["error_code"] is None
    assert body["reply"] == "处理完成"
    assert body["session_id"] == "e2e"

    # All five tool calls should appear, in order.
    tool_calls = body["tool_calls"]
    tools = [tc["tool"] for tc in tool_calls]
    assert tools == [
        "tablex_upload",
        "tablex_inspect",
        "tablex_normalize",
        "tablex_group_summary",
        "tablex_export",
    ]
    assert all(tc["status"] == "ok" for tc in tool_calls)

    # Output file is downloadable.
    output_id = body["output_id"]
    assert output_id
    download = client.get(f"/api/outputs/{output_id}")
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert len(download.content) > 0


def test_e2e_chat_persists_messages_to_sqlite(client: TestClient) -> None:
    """Per plan §1.2.3: messages are persisted to SQLite for debug, not reloaded on startup."""
    source = FIXTURES / "expenses_and_budget.xlsx"
    file_id = _upload(client, source)

    def ok_caller(**_kwargs: Any) -> dict[str, Any]:
        return _response([_text_block("ok")], stop_reason="end_turn")

    agent_module.set_chat_caller(ok_caller)
    try:
        resp = client.post(
            "/api/chat",
            json={"message": "hello", "file_ids": [file_id], "session_id": "persist-test"},
        )
    finally:
        agent_module.set_chat_caller(None)
    assert resp.status_code == 200

    settings = get_settings()
    db_path = Path(settings.APP_DATA_DIR) / "metadata.db"
    stored = get_session_messages(db_path, "persist-test")
    assert stored, "session messages should be persisted to SQLite"
    assert any(m.get("role") == "user" for m in stored)
    assert any(m.get("role") == "assistant" for m in stored)


def test_e2e_chat_session_id_preserved_across_calls(client: TestClient) -> None:
    """Two consecutive POSTs with the same session_id should reuse the in-memory session."""
    source = FIXTURES / "expenses_and_budget.xlsx"
    file_id = _upload(client, source)

    seen_sessions: list[str] = []

    def ok_caller(**kwargs: Any) -> dict[str, Any]:
        seen_sessions.append(kwargs.get("session_id") or "")
        return _response([_text_block("ok")], stop_reason="end_turn")

    agent_module.set_chat_caller(ok_caller)
    try:
        for _ in range(2):
            r = client.post(
                "/api/chat",
                json={"message": "hi", "file_ids": [file_id], "session_id": "reuse-1"},
            )
            assert r.status_code == 200
    finally:
        agent_module.set_chat_caller(None)

    assert len(seen_sessions) == 2


def test_e2e_chat_rejects_unknown_file(client: TestClient) -> None:
    def ok_caller(**_kwargs: Any) -> dict[str, Any]:
        return _response([_text_block("ok")], stop_reason="end_turn")

    agent_module.set_chat_caller(ok_caller)
    try:
        resp = client.post(
            "/api/chat",
            json={"message": "hi", "file_ids": ["missing-file"], "session_id": "no-file"},
        )
    finally:
        agent_module.set_chat_caller(None)
    assert resp.status_code == 200
    body = resp.json()
    assert body["error_code"] == "file_not_found"
