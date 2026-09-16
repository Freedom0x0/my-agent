"""Tests for the agent loop (mocked MiniMax API)."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pandas as pd
import pytest
from openpyxl import Workbook

from backend.app.mcp import agent as agent_module
from backend.app.mcp.agent import ChatError, process_chat
from backend.app.mcp.schemas import MAX_TOOL_CALLS
from backend.app.mcp.session import SessionStore
from backend.app.config import get_settings


class _FakeSettings:
    APP_DATA_DIR = "runtime"
    MODEL_BASE_URL = "https://example.test"
    MODEL_API_KEY = "fake-key"
    MODEL_NAME = "fake-model"


@pytest.fixture()
def sample_workbook(tmp_path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "明细"
    ws.append(["部门", "订单号", "金额"])
    ws.append(["研发", "A001", "1,200"])
    ws.append(["销售", "A002", "800"])
    ws.append(["研发", "A003", "2,000"])
    out = tmp_path / "sample.xlsx"
    wb.save(out)
    return out


@pytest.fixture()
def session_store(tmp_path: Path) -> SessionStore:
    out = tmp_path / "outputs"
    out.mkdir(parents=True, exist_ok=True)
    return SessionStore(out)


def _make_response(content: list[dict[str, Any]], stop_reason: str = "end_turn") -> dict[str, Any]:
    return {"stop_reason": stop_reason, "content": content}


def _text_block(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def _tool_use_block(tool_use_id: str, name: str, input_dict: dict[str, Any]) -> dict[str, Any]:
    return {"type": "tool_use", "id": tool_use_id, "name": name, "input": input_dict}


def test_process_chat_end_turn_no_tools(session_store: SessionStore, monkeypatch) -> None:
    monkeypatch.setattr(agent_module, "_default_chat_caller",
                        lambda **kwargs: _make_response([_text_block("Hello back")], stop_reason="end_turn"))
    response = process_chat("sid", "hi", [], store=session_store, settings=_FakeSettings())
    assert response.reply == "Hello back"
    assert response.error_code is None
    assert response.tool_calls == []


def test_process_chat_executes_tool_then_text(session_store: SessionStore, sample_workbook: Path, monkeypatch) -> None:
    # Register the file in the session so handler can find it.
    sess = session_store.get_or_create("sid")
    sess.files["file-001"] = {
        "path": str(sample_workbook), "sha256": "x", "original_name": "sample.xlsx",
    }
    # Pre-load tables as if tablex_upload ran.
    from backend.app.domain.parser import load_tables

    for n, df in load_tables(sample_workbook).items():
        sess.tables[f"file-001::{n}"] = df

    # First call returns a tool_use (tablex_normalize); second returns text.
    responses = [
        _make_response(
            [_tool_use_block("tu-1", "tablex_normalize", {
                "file_id": "file-001", "sheet": "明细", "columns": ["金额"], "target_type": "number",
            })],
            stop_reason="tool_use",
        ),
        _make_response([_text_block("已统一金额格式。")], stop_reason="end_turn"),
    ]

    def fake_caller(**kwargs):
        return responses.pop(0)

    monkeypatch.setattr(agent_module, "_default_chat_caller", fake_caller)

    response = process_chat("sid", "统一金额格式", ["file-001"], store=session_store, settings=_FakeSettings())
    assert response.reply == "已统一金额格式。"
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0]["tool"] == "tablex_normalize"
    assert response.tool_calls[0]["status"] == "ok"
    # tables were actually mutated
    assert sess.audit_events and sess.audit_events[0].operation == "normalize"


def test_process_chat_max_tool_calls_exceeded(session_store: SessionStore, sample_workbook: Path, monkeypatch) -> None:
    sess = session_store.get_or_create("sid")
    sess.files["file-001"] = {
        "path": str(sample_workbook), "sha256": "x", "original_name": "sample.xlsx",
    }
    from backend.app.domain.parser import load_tables

    for n, df in load_tables(sample_workbook).items():
        sess.tables[f"file-001::{n}"] = df

    # Always returns a tool_use → loop should exceed MAX_TOOL_CALLS.
    monkeypatch.setattr(agent_module, "_default_chat_caller",
                        lambda **kwargs: _make_response(
                            [_tool_use_block("tu-1", "tablex_normalize", {
                                "file_id": "file-001", "sheet": "明细",
                                "columns": ["金额"], "target_type": "number",
                            })],
                            stop_reason="tool_use",
                        ))

    with pytest.raises(ChatError) as exc_info:
        process_chat("sid", "循环", ["file-001"], store=session_store, settings=_FakeSettings())
    assert exc_info.value.code == "too_many_steps"
    # verify we ran MAX_TOOL_CALLS iterations (each iteration adds one tool_call log)
    assert len(sess.tool_calls_log) == MAX_TOOL_CALLS


def test_process_chat_handles_validation_failure(session_store: SessionStore, sample_workbook: Path, monkeypatch) -> None:
    sess = session_store.get_or_create("sid")
    sess.files["file-001"] = {
        "path": str(sample_workbook), "sha256": "x", "original_name": "sample.xlsx",
    }
    from backend.app.domain.parser import load_tables

    for n, df in load_tables(sample_workbook).items():
        sess.tables[f"file-001::{n}"] = df

    responses = [
        _make_response(
            [_tool_use_block("tu-1", "tablex_normalize", {
                "file_id": "file-001", "sheet": "不存在的", "columns": ["金额"], "target_type": "number",
            })],
            stop_reason="tool_use",
        ),
        _make_response([_text_block("重新规划")], stop_reason="end_turn"),
    ]
    monkeypatch.setattr(agent_module, "_default_chat_caller", lambda **kwargs: responses.pop(0))

    response = process_chat("sid", "test", ["file-001"], store=session_store, settings=_FakeSettings())
    assert response.reply == "重新规划"
    # One tool call log with error status
    assert response.tool_calls[0]["status"] == "error"


def test_process_chat_model_not_configured(session_store: SessionStore) -> None:
    class BadSettings:
        APP_DATA_DIR = "runtime"
        MODEL_BASE_URL = ""
        MODEL_API_KEY = ""
        MODEL_NAME = ""

    with pytest.raises(ChatError) as exc_info:
        process_chat("sid", "hi", [], store=session_store, settings=BadSettings())
    assert exc_info.value.code == "model_not_configured"


def test_process_chat_max_tokens_stop_reason(session_store: SessionStore, monkeypatch) -> None:
    monkeypatch.setattr(agent_module, "_default_chat_caller",
                        lambda **kwargs: _make_response([_text_block("...")], stop_reason="max_tokens"))
    response = process_chat("sid", "hi", [], store=session_store, settings=_FakeSettings())
    assert response.error_code == "model_truncated"


def test_process_chat_unknown_stop_reason_raises(session_store: SessionStore, monkeypatch) -> None:
    monkeypatch.setattr(agent_module, "_default_chat_caller",
                        lambda **kwargs: _make_response([], stop_reason="wat"))
    with pytest.raises(ChatError) as exc_info:
        process_chat("sid", "hi", [], store=session_store, settings=_FakeSettings())
    assert exc_info.value.code == "model_unknown_stop_reason"


def test_process_chat_empty_message_raises(session_store: SessionStore, monkeypatch) -> None:
    monkeypatch.setattr(agent_module, "_default_chat_caller",
                        lambda **kwargs: _make_response([_text_block("ok")], stop_reason="end_turn"))
    with pytest.raises(ChatError) as exc_info:
        process_chat("sid", "   ", [], store=session_store, settings=_FakeSettings())
    assert exc_info.value.code == "invalid_request"


def test_process_chat_file_not_found_raises(session_store: SessionStore, monkeypatch) -> None:
    monkeypatch.setattr(agent_module, "_default_chat_caller",
                        lambda **kwargs: _make_response([_text_block("ok")], stop_reason="end_turn"))
    with pytest.raises(ChatError) as exc_info:
        process_chat("sid", "hi", ["missing-file"], store=session_store, settings=_FakeSettings())
    assert exc_info.value.code == "file_not_found"


def test_process_chat_first_message_includes_file_context(session_store: SessionStore, sample_workbook: Path, monkeypatch) -> None:
    sess = session_store.get_or_create("sid")
    sess.files["file-001"] = {
        "path": str(sample_workbook), "sha256": "x", "original_name": "sample.xlsx",
    }

    seen_messages: list[list[dict[str, Any]]] = []

    def capture(**kwargs):
        seen_messages.append(kwargs["messages"])
        return _make_response([_text_block("ok")], stop_reason="end_turn")

    monkeypatch.setattr(agent_module, "_default_chat_caller", capture)

    process_chat("sid", "汇总金额", ["file-001"], store=session_store, settings=_FakeSettings())
    first_user = seen_messages[0][0]
    assert "file-001" in first_user["content"]
    assert "汇总金额" in first_user["content"]


def test_set_chat_caller_restores_default(monkeypatch) -> None:
    from backend.app.mcp.agent import set_chat_caller

    custom = lambda **kwargs: {"stop_reason": "end_turn", "content": []}
    set_chat_caller(custom)
    assert agent_module._default_chat_caller is custom
    set_chat_caller(None)
    assert agent_module._default_chat_caller is agent_module.minimax_chat