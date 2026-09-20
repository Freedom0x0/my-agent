"""End-to-end test for the MCP / MiniMax chat flow.

- Spins up FastAPI TestClient.
- Uploads fixtures/expenses_and_budget.xlsx via POST /api/files.
- Drives POST /api/chat with a scripted MiniMax response queue (model is mocked).
- Verifies the model *compiles* a workflow graph, that nothing is executed, and
  that the graph + stage are readable back over HTTP and from SQLite.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app.config import get_settings
from backend.app.db import get_session_messages, get_workflow, init_db
from backend.app.main import create_app
from backend.app.mcp import agent as agent_module
from backend.app.mcp.session import get_session_store, reset_session_store
from backend.app.mcp.workflow import META_TOOL_NAME


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


def _workflow_graph(file_id: str) -> dict[str, Any]:
    return {
        "nodes": [
            {"id": "n_up", "label": "读取收支明细", "tool": "tablex_upload", "input": {"file_id": file_id}},
            {
                "id": "n_sum",
                "label": "按部门汇总",
                "tool": "tablex_group_summary",
                "input": {"group_by": ["部门"], "metrics": {"金额": ["sum"]}, "output_sheet": "汇总结果"},
            },
        ],
        "edges": [{"from_node": "n_up", "to_node": "n_sum", "to_param": "sheet"}],
    }


def test_e2e_chat_compiles_a_graph_and_stops_for_approval(client: TestClient) -> None:
    """upload -> chat (mocked) -> graph stored, stage awaiting_approval, nothing ran."""
    source = FIXTURES / "expenses_and_budget.xlsx"
    assert source.exists(), f"fixture missing: {source}"

    file_id = _upload(client, source)

    # The model first tries to call a node-type tool directly (rejected), then
    # submits the graph. The turn must stop right there.
    responses = [
        _response(
            [_tool_use_block("tu-1", "tablex_upload", {"file_id": file_id})],
            stop_reason="tool_use",
        ),
        _response(
            [_tool_use_block("tu-2", META_TOOL_NAME, _workflow_graph(file_id))],
            stop_reason="tool_use",
        ),
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
    assert body["session_id"] == "e2e"
    assert body["stage"] == "awaiting_approval"
    assert [n["id"] for n in body["graph"]["nodes"]] == ["n_up", "n_sum"]

    # Direct call rejected, graph submission accepted — and nothing was executed.
    assert [(tc["tool"], tc["status"]) for tc in body["tool_calls"]] == [
        ("tablex_upload", "error"),
        (META_TOOL_NAME, "ok"),
    ]
    assert body["output_id"] is None

    # The graph is the truth: it's readable back over HTTP with its derived seq.
    workflow = client.get("/api/sessions/e2e/workflow").json()
    assert workflow["stage"] == "awaiting_approval"
    assert [n["seq"] for n in workflow["nodes"]] == [1, 2]
    assert workflow["nodes"][1]["label"] == "按部门汇总"
    assert workflow["edges"] == [{"from_node": "n_up", "to_node": "n_sum", "to_param": "sheet"}]

    # And in SQLite.
    db_path = Path(get_settings().APP_DATA_DIR) / "metadata.db"
    saved = get_workflow(db_path, "e2e")
    assert saved is not None and saved["stage"] == "awaiting_approval"


def test_e2e_stage_agrees_between_response_memory_and_db(client: TestClient) -> None:
    """Regression: a text-only follow-up turn must not leave a stale stage in SQLite.

    The graph is still unapproved, so `awaiting_approval` is the truth — if the
    turn reported `drafting` while the DB said `awaiting_approval`, the approval
    subtask would act on a graph the user may have just asked to change.
    """
    file_id = _upload(client, FIXTURES / "expenses_and_budget.xlsx")

    responses = [
        _response([_tool_use_block("tu-1", META_TOOL_NAME, _workflow_graph(file_id))], stop_reason="tool_use"),
        _response([_text_block("还有什么要改的吗？")], stop_reason="end_turn"),
    ]
    agent_module.set_chat_caller(lambda **_kw: responses.pop(0))
    try:
        first = client.post(
            "/api/chat",
            json={"message": "按部门汇总", "file_ids": [file_id], "session_id": "stage-drift"},
        ).json()
        second = client.post(
            "/api/chat",
            json={"message": "这张图是什么意思？", "file_ids": [file_id], "session_id": "stage-drift"},
        ).json()
    finally:
        agent_module.set_chat_caller(None)

    assert first["stage"] == "awaiting_approval"
    assert second["stage"] == "awaiting_approval"
    assert second["reply"] == "还有什么要改的吗？"
    # Both readers agree, and a reloaded session does too.
    assert client.get("/api/sessions/stage-drift/workflow").json()["stage"] == "awaiting_approval"
    assert get_session_store().get("stage-drift").stage == "awaiting_approval"


def test_e2e_workflow_route_404s_before_a_graph_exists(client: TestClient) -> None:
    assert client.get("/api/sessions/no-graph-yet/workflow").status_code == 404


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
