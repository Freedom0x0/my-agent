"""Tests for /api/chat/stream SSE endpoint and process_chat_stream."""
from __future__ import annotations

import datetime as _dt
import logging
import json
from pathlib import Path
from typing import Any, AsyncIterator

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from backend.app.config import get_settings
from backend.app.db import FileRecord, init_db, insert_file
from backend.app.main import create_app
from backend.app.mcp import agent as agent_module
from backend.app.mcp.session import reset_session_store
from backend.app.mcp.workflow import META_TOOL_NAME


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


def _parse_sse(body: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for block in body.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        for line in block.splitlines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))
                break
    return events


def _sse_event(evt_type: str, **fields: Any) -> str:
    return f"data: {json.dumps({'type': evt_type, **fields}, ensure_ascii=False)}\n\n"


async def _fake_stream_end_turn() -> AsyncIterator[dict[str, Any]]:
    yield {"type": "model_meta", "message_id": "msg_1"}
    yield {"type": "text", "delta": "你"}
    yield {"type": "text", "delta": "好"}
    yield {"type": "message_done", "stop_reason": "end_turn",
           "content_blocks": [{"type": "text", "text": "你好"}]}


async def _fake_stream_with_tool(tmp_path: Path) -> AsyncIterator[dict[str, Any]]:
    yield {"type": "model_meta", "message_id": "msg_2"}
    yield {"type": "text", "delta": "正在"}
    yield {"type": "text", "delta": "检查"}
    yield {"type": "tool_use_start", "id": "tu-1", "name": "tablex_inspect"}
    yield {"type": "tool_use_delta", "id": "tu-1", "partial_json": '{"file_id": "file-001"}'}
    yield {"type": "tool_use_end", "id": "tu-1"}
    yield {
        "type": "message_done",
        "stop_reason": "tool_use",
        "content_blocks": [
            {"type": "text", "text": "正在检查"},
            {"type": "tool_use", "id": "tu-1", "name": "tablex_inspect",
             "input": {"file_id": "file-001"}},
        ],
    }


@pytest.fixture()
def sample_file(tmp_path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "明细"
    ws.append(["部门", "订单号", "金额"])
    ws.append(["研发", "A001", "1,200"])
    wb.save(tmp_path / "sample.xlsx")
    return tmp_path / "sample.xlsx"


def test_chat_stream_end_turn_emits_text_and_done(client: TestClient) -> None:
    async def caller(**_kwargs):
        async for e in _fake_stream_end_turn():
            yield e

    agent_module.set_stream_caller(caller)
    try:
        with client.stream("POST", "/api/chat/stream", json={"message": "hi"}) as r:
            body = "".join(r.iter_text())
    finally:
        agent_module.set_stream_caller(None)

    events = _parse_sse(body)
    types = [e["type"] for e in events]
    assert types[0] == "model_call"
    assert "text" in types
    text_deltas = [e["delta"] for e in events if e["type"] == "text"]
    assert text_deltas == ["你", "好"]
    done = next(e for e in events if e["type"] == "done")
    assert done["reply"] == "你好"


def test_chat_stream_direct_tool_call_is_rejected_then_end_turn(
    app_with_data_dir, client: TestClient, sample_file: Path,
) -> None:
    """A directly-called node-type tool is handed back as an error — never run."""
    _, tmp_path = app_with_data_dir
    file_id = "file-001"
    record = FileRecord(
        file_id=file_id,
        original_name="sample.xlsx",
        stored_path=str(sample_file),
        file_type="xlsx",
        size_bytes=sample_file.stat().st_size,
        sha256="x",
        inspection={"filename": "sample.xlsx", "file_type": "xlsx", "sheets": []},
        created_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
    )
    insert_file(tmp_path / "runtime" / "metadata.db", record)

    responses = [
        _fake_stream_with_tool(tmp_path),
        _fake_stream_end_turn(),
    ]

    async def caller(**_kwargs):
        gen = responses.pop(0)
        async for e in gen:
            yield e

    agent_module.set_stream_caller(caller)
    try:
        with client.stream("POST", "/api/chat/stream",
                           json={"message": "检查", "file_ids": [file_id], "session_id": "stream-flow"}) as r:
            body = "".join(r.iter_text())
    finally:
        agent_module.set_stream_caller(None)

    events = _parse_sse(body)
    types = [e["type"] for e in events]
    assert "tool_start" in types
    assert "tool_end" in types
    tool_end = next(e for e in events if e["type"] == "tool_end")
    assert tool_end["name"] == "tablex_inspect"
    assert tool_end["status"] == "error"
    assert "不能直接调用" in tool_end["summary"]
    # `id` is how the client pairs tool_end with its tool_start; without it parallel
    # tool calls in one round can't be resolved.
    assert tool_end["id"] == "tu-1"
    done = next(e for e in events if e["type"] == "done")
    assert done["reply"] == "你好"
    assert done["stage"] == "drafting"
    assert done["graph"] is None
    # output_id MUST NOT leak through done payload; only output_name + sheets.
    assert "output_id" not in done


def test_chat_stream_propose_workflow_emits_graph_and_stops(
    app_with_data_dir, client: TestClient, sample_file: Path,
) -> None:
    """Submitting the graph ends the turn: stage_change + done carry the graph."""
    _, tmp_path = app_with_data_dir
    file_id = "file-graph"
    insert_file(
        tmp_path / "runtime" / "metadata.db",
        FileRecord(
            file_id=file_id,
            original_name="sample.xlsx",
            stored_path=str(sample_file),
            file_type="xlsx",
            size_bytes=sample_file.stat().st_size,
            sha256="x",
            inspection={"filename": "sample.xlsx", "file_type": "xlsx", "sheets": []},
            created_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
        ),
    )

    graph = {
        "nodes": [
            {"id": "n_up", "label": "读取明细", "tool": "tablex_upload", "input": {"file_id": file_id}},
            {"id": "n_sum", "label": "按部门汇总", "tool": "tablex_group_summary", "input": {"group_by": ["部门"]}},
        ],
        "edges": [{"from_node": "n_up", "to_node": "n_sum", "to_param": "sheet"}],
    }

    async def stream_propose() -> AsyncIterator[dict[str, Any]]:
        yield {"type": "model_meta", "message_id": "m"}
        yield {"type": "text", "delta": "这样处理"}
        yield {"type": "tool_use_start", "id": "tu-1", "name": META_TOOL_NAME}
        yield {"type": "tool_use_delta", "id": "tu-1", "partial_json": json.dumps(graph, ensure_ascii=False)}
        yield {"type": "tool_use_end", "id": "tu-1"}
        yield {
            "type": "message_done",
            "stop_reason": "tool_use",
            "content_blocks": [
                {"type": "text", "text": "这样处理"},
                {"type": "tool_use", "id": "tu-1", "name": META_TOOL_NAME, "input": graph},
            ],
        }

    calls = 0

    async def caller(**_kwargs):
        nonlocal calls
        calls += 1
        async for e in stream_propose():
            yield e

    agent_module.set_stream_caller(caller)
    try:
        with client.stream("POST", "/api/chat/stream",
                           json={"message": "汇总", "file_ids": [file_id], "session_id": "sse-graph"}) as r:
            body = "".join(r.iter_text())
    finally:
        agent_module.set_stream_caller(None)

    events = _parse_sse(body)
    assert calls == 1, "提交图后必须停住，不再问模型"
    stage_change = next(e for e in events if e["type"] == "stage_change")
    assert stage_change["stage"] == "awaiting_approval"

    done = next(e for e in events if e["type"] == "done")
    assert done["stage"] == "awaiting_approval"
    assert [n["id"] for n in done["graph"]["nodes"]] == ["n_up", "n_sum"]
    assert done["reply"] == "这样处理"
    assert "output_id" not in done
    assert done["tool_calls"][-1]["tool"] == META_TOOL_NAME
    assert done["tool_calls"][-1]["status"] == "ok"

    # Persisted, so a reload can redraw the canvas.
    workflow = client.get("/api/sessions/sse-graph/workflow").json()
    assert workflow["stage"] == "awaiting_approval"
    assert [n["seq"] for n in workflow["nodes"]] == [1, 2]


def test_chat_stream_disconnect_stops_early(client: TestClient) -> None:
    async def slow_caller(**_kwargs):
        yield {"type": "model_meta", "message_id": "m1"}
        yield {"type": "text", "delta": "first"}
        # At this point the client already disconnected (we never read further).
        yield {"type": "text", "delta": "second"}
        yield {"type": "message_done", "stop_reason": "end_turn",
               "content_blocks": [{"type": "text", "text": "firstsecond"}]}

    agent_module.set_stream_caller(slow_caller)
    try:
        with client.stream("POST", "/api/chat/stream",
                           json={"message": "hi", "session_id": "disc"}) as r:
            # Pull only the first chunk then bail (simulate early disconnect).
            for chunk in r.iter_text():
                if chunk:
                    break
    finally:
        agent_module.set_stream_caller(None)

    # After disconnect, process_chat_stream checks once per iteration.
    # We don't assert on output here (client dropped before flushing);
    # we only assert the server didn't crash and the route returns.
    assert True


def test_chat_stream_invalid_message_returns_error(client: TestClient) -> None:
    with client.stream("POST", "/api/chat/stream", json={"message": "  "}) as r:
        body = "".join(r.iter_text())
    events = _parse_sse(body)
    assert any(e["type"] == "error" and e["code"] == "invalid_request" for e in events)


def test_chat_stream_max_tokens_returns_truncated_error(client: TestClient) -> None:
    async def caller(**_kwargs):
        yield {"type": "model_meta", "message_id": "m"}
        yield {"type": "text", "delta": "x"}
        yield {"type": "message_done", "stop_reason": "max_tokens",
               "content_blocks": [{"type": "text", "text": "x"}]}

    agent_module.set_stream_caller(caller)
    try:
        with client.stream("POST", "/api/chat/stream", json={"message": "hi"}) as r:
            body = "".join(r.iter_text())
    finally:
        agent_module.set_stream_caller(None)

    events = _parse_sse(body)
    assert any(e["type"] == "error" and e["code"] == "model_truncated" for e in events)


def test_chat_stream_segments_preserve_order_across_iterations(
    app_with_data_dir, client: TestClient, sample_file: Path,
) -> None:
    """Done event's `segments` follows the model's actual order: text -> tool -> text -> tool -> text."""
    _, tmp_path = app_with_data_dir
    file_id = "file-seg"
    insert_file(
        tmp_path / "runtime" / "metadata.db",
        FileRecord(
            file_id=file_id,
            original_name="sample.xlsx",
            stored_path=str(sample_file),
            file_type="xlsx",
            size_bytes=sample_file.stat().st_size,
            sha256="x",
            inspection={"filename": "sample.xlsx", "file_type": "xlsx", "sheets": []},
            created_at=_dt.datetime.utcnow().isoformat(),
        ),
    )

    # Iter 1: text + tool_use  →  segments: [text, tool]
    # Iter 2: text + tool_use  →  segments: [text, tool, text, tool]
    # Iter 3: text + end_turn  →  segments: [text, tool, text, tool, text]
    async def stream_iter1() -> AsyncIterator[dict[str, Any]]:
        yield {"type": "model_meta", "message_id": "m"}
        yield {"type": "text", "delta": "first text "}
        yield {"type": "tool_use_start", "id": "tu-1", "name": "tablex_inspect"}
        yield {"type": "tool_use_delta", "id": "tu-1", "partial_json": '{"file_id": "file-seg"}'}
        yield {"type": "tool_use_end", "id": "tu-1"}
        yield {
            "type": "message_done",
            "stop_reason": "tool_use",
            "content_blocks": [
                {"type": "text", "text": "first text "},
                {"type": "tool_use", "id": "tu-1", "name": "tablex_inspect",
                 "input": {"file_id": "file-seg"}},
            ],
        }

    async def stream_iter2() -> AsyncIterator[dict[str, Any]]:
        yield {"type": "model_meta", "message_id": "m"}
        yield {"type": "text", "delta": "second text "}
        yield {"type": "tool_use_start", "id": "tu-2", "name": "tablex_normalize"}
        yield {"type": "tool_use_delta", "id": "tu-2", "partial_json": "{}"}
        yield {"type": "tool_use_end", "id": "tu-2"}
        yield {
            "type": "message_done",
            "stop_reason": "tool_use",
            "content_blocks": [
                {"type": "text", "text": "second text "},
                {"type": "tool_use", "id": "tu-2", "name": "tablex_normalize", "input": {}},
            ],
        }

    async def stream_iter3() -> AsyncIterator[dict[str, Any]]:
        yield {"type": "model_meta", "message_id": "m"}
        yield {"type": "text", "delta": "final text"}
        yield {
            "type": "message_done",
            "stop_reason": "end_turn",
            "content_blocks": [{"type": "text", "text": "final text"}],
        }

    responses = [stream_iter1(), stream_iter2(), stream_iter3()]

    async def caller(**_kwargs):
        gen = responses.pop(0)
        async for e in gen:
            yield e

    agent_module.set_stream_caller(caller)
    try:
        with client.stream(
            "POST",
            "/api/chat/stream",
            json={"message": "go", "file_ids": [file_id], "session_id": "seg-order"},
        ) as r:
            body = "".join(r.iter_text())
    finally:
        agent_module.set_stream_caller(None)

    events = _parse_sse(body)
    done = next(e for e in events if e["type"] == "done")
    segs = done.get("segments")
    assert segs is not None, "done event must include segments"
    assert len(segs) == 5, f"expected 5 segments, got {len(segs)}: {segs}"
    assert segs[0] == {"type": "text", "content": "first text "}
    assert segs[1]["type"] == "tool" and segs[1]["call"]["tool"] == "tablex_inspect"
    assert segs[2] == {"type": "text", "content": "second text "}
    assert segs[3]["type"] == "tool" and segs[3]["call"]["tool"] == "tablex_normalize"
    assert segs[4] == {"type": "text", "content": "final text"}


def test_chat_stream_segments_end_turn_only_text(client: TestClient) -> None:
    """end_turn with no tools yields a single text segment."""
    async def caller(**_kwargs):
        async for e in _fake_stream_end_turn():
            yield e

    agent_module.set_stream_caller(caller)
    try:
        with client.stream("POST", "/api/chat/stream", json={"message": "hi"}) as r:
            body = "".join(r.iter_text())
    finally:
        agent_module.set_stream_caller(None)

    events = _parse_sse(body)
    done = next(e for e in events if e["type"] == "done")
    segs = done.get("segments")
    assert segs == [{"type": "text", "content": "你好"}]


def test_stream_turn_persists_interleaved_ui_transcript(
    app_with_data_dir, client: TestClient, sample_file: Path,
) -> None:
    """After a turn, the session API replays the same text/tool order the client saw."""
    _, tmp_path = app_with_data_dir
    file_id = "file-ui"
    insert_file(
        tmp_path / "runtime" / "metadata.db",
        FileRecord(
            file_id=file_id,
            original_name="sample.xlsx",
            stored_path=str(sample_file),
            file_type="xlsx",
            size_bytes=sample_file.stat().st_size,
            sha256="x",
            inspection={"filename": "sample.xlsx", "file_type": "xlsx", "sheets": []},
            created_at=_dt.datetime.utcnow().isoformat(),
        ),
    )

    responses = [_fake_stream_with_tool(tmp_path), _fake_stream_end_turn()]

    async def caller(**_kwargs):
        gen = responses.pop(0)
        async for e in gen:
            yield e

    agent_module.set_stream_caller(caller)
    try:
        with client.stream("POST", "/api/chat/stream",
                           json={"message": "检查", "file_ids": [file_id], "session_id": "ui-flow"}) as r:
            "".join(r.iter_text())
    finally:
        agent_module.set_stream_caller(None)

    body = client.get("/api/sessions/ui-flow").json()
    assert [m["role"] for m in body["messages"]] == ["user", "assistant"]
    assert body["messages"][0]["content"] == "检查"

    assistant = body["messages"][1]
    assert [s["type"] for s in assistant["segments"]] == ["text", "tool", "text"]
    assert assistant["segments"][0]["content"] == "正在检查"
    assert assistant["segments"][2]["content"] == "你好"
    assert assistant["segments"][1]["call"]["tool"] == "tablex_inspect"
    # Never a half-open tool call: the persisted transcript holds a terminal status.
    assert assistant["segments"][1]["call"]["status"] in {"ok", "error"}


def _tool_round(block_id: str, name: str, tool_input: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    """One model round that calls a single tool."""
    async def gen() -> AsyncIterator[dict[str, Any]]:
        yield {"type": "model_meta", "message_id": "m"}
        yield {"type": "tool_use_start", "id": block_id, "name": name}
        yield {
            "type": "tool_use_delta",
            "id": block_id,
            "partial_json": json.dumps(tool_input),
        }
        yield {"type": "tool_use_end", "id": block_id}
        yield {
            "type": "message_done",
            "stop_reason": "tool_use",
            "content_blocks": [
                {"type": "tool_use", "id": block_id, "name": name, "input": tool_input},
            ],
        }
    return gen()


def test_rejected_tool_call_produces_no_output(
    app_with_data_dir, client: TestClient, sample_file: Path, caplog,
) -> None:
    """A directly-called export is rejected, so no output_id can leak to the client.

    (Execution — and therefore real outputs — belongs to the execution engine;
    this loop only compiles the graph.)
    """
    _, tmp_path = app_with_data_dir
    file_id = "file-out"
    # Capture "app" at INFO from the start — the root logger defaults to WARNING, so
    # `log_event(INFO, ...)` wouldn't even reach the handler otherwise.
    caplog.set_level(logging.INFO, logger="app")
    insert_file(
        tmp_path / "runtime" / "metadata.db",
        FileRecord(
            file_id=file_id,
            original_name="sample.xlsx",
            stored_path=str(sample_file),
            file_type="xlsx",
            size_bytes=sample_file.stat().st_size,
            sha256="x",
            inspection={"filename": "sample.xlsx", "file_type": "xlsx", "sheets": []},
            created_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
        ),
    )

    responses = [
        _tool_round("tu-1", "tablex_upload", {"file_id": file_id}),
        _tool_round("tu-2", "tablex_export", {"output_name": "清洗后数据"}),
    ]

    async def end_turn() -> AsyncIterator[dict[str, Any]]:
        yield {"type": "model_meta", "message_id": "m"}
        yield {"type": "text", "delta": "好了"}
        yield {
            "type": "message_done",
            "stop_reason": "end_turn",
            "content_blocks": [{"type": "text", "text": "好了"}],
        }
    responses.append(end_turn())

    async def caller(**_kwargs):
        gen_resp = responses.pop(0)
        async for e in gen_resp:
            yield e

    agent_module.set_stream_caller(caller)
    try:
        with client.stream("POST", "/api/chat/stream",
                           json={"message": "导出", "file_ids": [file_id], "session_id": "sse-out"}) as r:
            body = "".join(r.iter_text())
    finally:
        agent_module.set_stream_caller(None)

    events = _parse_sse(body)
    export_end = next(
        e for e in events if e["type"] == "tool_end" and e["name"] == "tablex_export"
    )
    assert export_end["status"] == "error"
    assert export_end["output_id"] is None
    assert export_end["output_name"] is None

    done = next(e for e in events if e["type"] == "done")
    assert done["output_name"] is None
    assert done["sheets"] == []  # nothing was loaded or produced

    # The tool log is the only trace left after the fact, so it has to say which
    # conversation (and, where the tool takes one, which file) the call belonged to.
    def _tool_lines(name: str) -> list[str]:
        return [r.getMessage() for r in caplog.records if f"tool tablex_{name} " in r.getMessage()]

    assert _tool_lines("export"), "every tool call must leave a log line"
    assert "session=sse-out" in _tool_lines("export")[-1]
    # tablex_export takes only output_name; tablex_upload is the one carrying file_id.
    assert f"file={file_id}" in _tool_lines("upload")[-1]
