"""Tests for the DAG execution engine (mcp/engine.py).

Everything runs a fake `node_runner` except the idempotency and HTTP tests, so the
scheduler's semantics (readiness, isolation, pause, reuse) are tested without a real
model or the domain layer getting in the way.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.app.config import get_settings
from backend.app.db import get_output, init_db, save_workflow
from backend.app.main import create_app
from backend.app.mcp.engine import (
    _execute_sync,
    mark_stale,
    transitive_downstream,
)
from backend.app.mcp.schemas import ToolCall, ToolResult
from backend.app.mcp.session import SessionStore, reset_session_store
from backend.app.mcp.workflow import WorkflowError, normalize_graph


def _graph(nodes: list[dict[str, Any]], edges: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return normalize_graph({"nodes": nodes, "edges": edges or []})


def _node(nid: str, tool: str = "tablex_normalize", **inp: Any) -> dict[str, Any]:
    return {"id": nid, "label": nid, "tool": tool, "input": inp}


def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, graph: dict[str, Any]):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "runtime"))
    get_settings.cache_clear()
    db_path = tmp_path / "runtime" / "metadata.db"
    init_db(db_path)
    store = SessionStore(tmp_path / "runtime" / "outputs", db_path=db_path)
    session = store.get_or_create("sid")
    session.graph = graph
    return session, store


def _run(session, store, runner=None, max_workers: int = 4) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    _execute_sync(session, store=store, emit=events.append, node_runner=runner, max_workers=max_workers)
    return events


def _table_runner(df: pd.DataFrame) -> Callable[[ToolCall, Any], ToolResult]:
    """A node runner that publishes `df` and reports it as its output sheet."""
    def runner(tool_call: ToolCall, shim: Any) -> ToolResult:
        shim.tables["fake::out"] = df.copy()
        return ToolResult(success=True, summary="ok", data={"output_sheet": "fake::out"})
    return runner


# ----- readiness & topological order --------------------------------------


def test_runs_in_dependency_order(tmp_path, monkeypatch) -> None:
    df = pd.DataFrame({"部门": ["研发", "销售"], "金额": [1, 2]})
    graph = _graph(
        [_node("n_up"), _node("n_mid"), _node("n_low")],
        [
            {"from_node": "n_up", "to_node": "n_mid", "to_param": "sheet"},
            {"from_node": "n_mid", "to_node": "n_low", "to_param": "sheet"},
        ],
    )
    session, store = _setup(tmp_path, monkeypatch, graph)

    order: list[str] = []
    lock = threading.Lock()

    def runner(tool_call, shim):
        with lock:
            order.append(tool_call.tool_use_id)
        return _table_runner(df)(tool_call, shim)

    _run(session, store, runner)

    assert order == ["n_up", "n_mid", "n_low"]
    assert [n["status"] for n in graph["nodes"]] == ["ok", "ok", "ok"]
    assert all(n["output"]["kind"] == "table" for n in graph["nodes"])


# ----- fan-out: parallelism + snapshot isolation --------------------------


def test_fanout_branches_overlap_in_time(tmp_path, monkeypatch) -> None:
    df = pd.DataFrame({"v": [1]})
    graph = _graph(
        [_node("n_up"), _node("n_a"), _node("n_b")],
        [
            {"from_node": "n_up", "to_node": "n_a", "to_param": "sheet"},
            {"from_node": "n_up", "to_node": "n_b", "to_param": "sheet"},
        ],
    )
    session, store = _setup(tmp_path, monkeypatch, graph)

    spans: dict[str, tuple[float, float]] = {}
    lock = threading.Lock()

    def runner(tool_call, shim):
        nid = tool_call.tool_use_id
        if nid == "n_up":
            return _table_runner(df)(tool_call, shim)
        start = time.perf_counter()
        time.sleep(0.25)
        with lock:
            spans[nid] = (start, time.perf_counter())
        key = next(iter(shim.tables))
        return ToolResult(success=True, summary="ok", data={"output_sheet": key})

    _run(session, store, runner)

    a_start, a_end = spans["n_a"]
    b_start, b_end = spans["n_b"]
    # Overlapping intervals: the later branch starts before the earlier one ends.
    assert max(a_start, b_start) < min(a_end, b_end)


def test_fanout_branches_read_the_same_upstream_snapshot(tmp_path, monkeypatch) -> None:
    """Branch A mutates its input in place; branch B must still see the original."""
    df = pd.DataFrame({"v": [1, 2, 3]})
    graph = _graph(
        [_node("n_up"), _node("n_a"), _node("n_b")],
        [
            {"from_node": "n_up", "to_node": "n_a", "to_param": "sheet"},
            {"from_node": "n_up", "to_node": "n_b", "to_param": "sheet"},
        ],
    )
    session, store = _setup(tmp_path, monkeypatch, graph)

    seen: dict[str, int] = {}

    def runner(tool_call, shim):
        nid = tool_call.tool_use_id
        if nid == "n_up":
            return _table_runner(df)(tool_call, shim)
        key = next(iter(shim.tables))
        seen[nid] = int(shim.tables[key]["v"].max())
        if nid == "n_a":
            shim.tables[key]["v"] = 999  # in-place mutation, as handlers do
        return ToolResult(success=True, summary="ok", data={"output_sheet": key})

    _run(session, store, runner)

    assert seen["n_a"] == 3
    assert seen["n_b"] == 3, "branch B saw branch A's mutation — tables were shared"


# ----- partial recompute --------------------------------------------------


def test_second_run_reuses_finished_nodes(tmp_path, monkeypatch) -> None:
    df = pd.DataFrame({"v": [1]})
    graph = _graph(
        [_node("n_up"), _node("n_mid")],
        [{"from_node": "n_up", "to_node": "n_mid", "to_param": "sheet"}],
    )
    session, store = _setup(tmp_path, monkeypatch, graph)

    calls: list[str] = []

    def runner(tool_call, shim):
        calls.append(tool_call.tool_use_id)
        return _table_runner(df)(tool_call, shim)

    _run(session, store, runner)
    assert calls == ["n_up", "n_mid"]

    events = _run(session, store, runner)
    assert calls == ["n_up", "n_mid"], "a second run must not re-execute ok nodes"
    assert all(n["cached"] for n in graph["nodes"])
    assert all(e.get("cached") for e in events if e["type"] == "node_end")


def test_run_stage_goes_executing_then_awaiting_approval(tmp_path, monkeypatch) -> None:
    df = pd.DataFrame({"v": [1]})
    graph = _graph([_node("n_up")])
    session, store = _setup(tmp_path, monkeypatch, graph)

    events = _run(session, store, _table_runner(df))

    stages = [e["stage"] for e in events if e["type"] == "stage_change"]
    assert stages == ["executing", "awaiting_approval"]
    assert session.stage == "awaiting_approval"
    done = [e for e in events if e["type"] == "done"][0]
    assert done["stage"] == "awaiting_approval"
    assert isinstance(done["total_ms"], int)


def test_node_events_carry_status_and_duration(tmp_path, monkeypatch) -> None:
    df = pd.DataFrame({"v": [1]})
    graph = _graph([_node("n_up")])
    session, store = _setup(tmp_path, monkeypatch, graph)

    events = _run(session, store, _table_runner(df))

    starts = [e for e in events if e["type"] == "node_start"]
    ends = [e for e in events if e["type"] == "node_end"]
    assert [e["node_id"] for e in starts] == ["n_up"]
    assert ends[0]["status"] == "ok"
    assert isinstance(ends[0]["duration_ms"], int)
    assert graph["nodes"][0]["duration_ms"] is not None


# ----- output on disk -----------------------------------------------------


def test_table_output_is_written_to_disk(tmp_path, monkeypatch) -> None:
    df = pd.DataFrame({"部门": ["研发"], "金额": [7]})
    graph = _graph([_node("n_up")])
    session, store = _setup(tmp_path, monkeypatch, graph)

    _run(session, store, _table_runner(df))

    output = graph["nodes"][0]["output"]
    assert output["kind"] == "table"
    assert output["row_count"] == 1
    assert output["columns"] == ["部门", "金额"]
    assert output["rows"][0] == ["研发", "7"]
    artifact = Path(get_settings().APP_DATA_DIR).resolve() / output["ref"]
    assert artifact.exists()


# ----- failure propagation ------------------------------------------------


def test_upstream_failure_blocks_downstream(tmp_path, monkeypatch) -> None:
    graph = _graph(
        [_node("n_up"), _node("n_down")],
        [{"from_node": "n_up", "to_node": "n_down", "to_param": "sheet"}],
    )
    session, store = _setup(tmp_path, monkeypatch, graph)

    def runner(tool_call, shim):
        if tool_call.tool_use_id == "n_up":
            return ToolResult(success=False, summary="boom", error="坏了")
        return ToolResult(success=True, summary="ok")

    events = _run(session, store, runner)

    by_id = {n["id"]: n for n in graph["nodes"]}
    assert by_id["n_up"]["status"] == "error"
    assert by_id["n_down"]["status"] == "error"
    assert "n_up" in by_id["n_down"]["error"]
    assert sum(1 for e in events if e["type"] == "node_start") == 1


# ----- pause --------------------------------------------------------------


def test_pause_stops_starting_new_nodes(tmp_path, monkeypatch) -> None:
    df = pd.DataFrame({"v": [1]})
    graph = _graph(
        [_node("n_1"), _node("n_2"), _node("n_3")],
        [
            {"from_node": "n_1", "to_node": "n_2", "to_param": "sheet"},
            {"from_node": "n_2", "to_node": "n_3", "to_param": "sheet"},
        ],
    )
    session, store = _setup(tmp_path, monkeypatch, graph)

    def runner(tool_call, shim):
        if tool_call.tool_use_id == "n_1":
            session.pause_requested = True  # pause while n_1 runs
        return _table_runner(df)(tool_call, shim)

    events = _run(session, store, runner)

    by_id = {n["id"]: n for n in graph["nodes"]}
    assert by_id["n_1"]["status"] == "ok"
    assert by_id["n_2"]["status"] == "pending"
    assert by_id["n_3"]["status"] == "pending"
    assert session.stage == "paused"
    assert events[-1]["type"] == "done" and events[-1]["stage"] == "paused"
    # The pause flag is consumed, so the next run starts clean.
    assert session.pause_requested is False


# ----- invalidation -------------------------------------------------------


def test_mark_stale_marks_transitive_downstream_only() -> None:
    graph = _graph(
        [_node("n_1"), _node("n_2"), _node("n_3"), _node("n_side")],
        [
            {"from_node": "n_1", "to_node": "n_2", "to_param": "sheet"},
            {"from_node": "n_2", "to_node": "n_3", "to_param": "sheet"},
            {"from_node": "n_1", "to_node": "n_side", "to_param": "sheet"},
        ],
    )
    for node in graph["nodes"]:
        node["status"] = "ok"

    affected = mark_stale(graph, "n_2")

    assert affected == ["n_3"]
    by_id = {n["id"]: n for n in graph["nodes"]}
    assert by_id["n_2"]["status"] == "ok"       # the edited node itself is not stale
    assert by_id["n_3"]["status"] == "stale"
    assert by_id["n_side"]["status"] == "ok"    # branch off the affected subgraph is untouched
    assert transitive_downstream(graph, "n_1") == {"n_2", "n_3", "n_side"}


# ----- to_param validation ------------------------------------------------


def test_to_param_typo_is_rejected() -> None:
    with pytest.raises(WorkflowError) as exc_info:
        _graph(
            [_node("n_up"), _node("n_sum", "tablex_group_summary", group_by=["部门"])],
            [{"from_node": "n_up", "to_node": "n_sum", "to_param": "sheets"}],
        )
    assert "sheets" in str(exc_info.value)


def test_to_param_object_and_ref_params_are_accepted() -> None:
    # compare.left_ref / join.left are real params; sheet is the universal one.
    graph = _graph(
        [
            _node("n_l"),
            _node("n_r"),
            _node("n_cmp", "tablex_compare", key_columns=["部门"]),
        ],
        [
            {"from_node": "n_l", "to_node": "n_cmp", "to_param": "left_ref"},
            {"from_node": "n_r", "to_node": "n_cmp", "to_param": "right_ref"},
        ],
    )
    assert len(graph["edges"]) == 2

    join_graph = _graph(
        [_node("n_l"), _node("n_r"), _node("n_j", "tablex_join")],
        [
            {"from_node": "n_l", "to_node": "n_j", "to_param": "left"},
            {"from_node": "n_r", "to_node": "n_j", "to_param": "right"},
        ],
    )
    assert len(join_graph["edges"]) == 2


def test_binding_fills_object_and_ref_params(tmp_path, monkeypatch) -> None:
    """The engine translates an edge into whatever shape the param expects."""
    df = pd.DataFrame({"部门": ["研发", "销售"], "金额": [1, 2]})
    graph = _graph(
        [_node("n_l"), _node("n_r"), _node("n_cmp", "tablex_compare", key_columns=["部门"])],
        [
            {"from_node": "n_l", "to_node": "n_cmp", "to_param": "left_ref"},
            {"from_node": "n_r", "to_node": "n_cmp", "to_param": "right_ref"},
        ],
    )
    session, store = _setup(tmp_path, monkeypatch, graph)

    captured: dict[str, Any] = {}

    def runner(tool_call, shim):
        if tool_call.tool_use_id in ("n_l", "n_r"):
            return _table_runner(df)(tool_call, shim)
        captured.update(tool_call.input)
        return ToolResult(success=True, summary="ok", data={"output_sheet": "对比结果"})

    _run(session, store, runner)

    assert captured["left_ref"] == "wf_n_l::n_l"
    assert captured["right_ref"] == "wf_n_r::n_r"


# ----- idempotent side effects (real export handler) ----------------------


def test_rerunning_a_side_effect_node_does_not_accumulate(tmp_path, monkeypatch) -> None:
    df = pd.DataFrame({"v": [1]})
    graph = _graph(
        [
            _node("n_up"),
            {"id": "n_out", "label": "导出", "tool": "tablex_export", "input": {"output_name": "结果"}},
        ],
        [{"from_node": "n_up", "to_node": "n_out", "to_param": "sheet"}],
    )
    session, store = _setup(tmp_path, monkeypatch, graph)

    # Only n_up is faked; n_out falls through to the real export handler.
    from backend.app.mcp.handlers import HANDLERS

    def runner_or_real(tool_call, shim):
        if tool_call.tool_use_id == "n_up":
            return _table_runner(df)(tool_call, shim)
        return HANDLERS[tool_call.name].fn(tool_call, shim)

    outputs_dir = Path(get_settings().APP_DATA_DIR).resolve() / "outputs"
    db_path = Path(get_settings().APP_DATA_DIR).resolve() / "metadata.db"

    _run(session, store, runner_or_real)
    first_files = sorted(p.name for p in outputs_dir.glob("*.xlsx"))
    assert first_files == ["n_out.xlsx"], "side-effect id must derive from the node id"
    assert graph["nodes"][1]["output"]["kind"] == "file"

    # Force a re-run (as a revise would) and assert nothing new piles up.
    graph["nodes"][1]["status"] = "pending"
    _run(session, store, runner_or_real)

    assert sorted(p.name for p in outputs_dir.glob("*.xlsx")) == first_files
    assert get_output(db_path, "n_out") is not None


# ----- HTTP surface -------------------------------------------------------


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("MODEL_BASE_URL", "https://example.test")
    monkeypatch.setenv("MODEL_API_KEY", "fake-key")
    monkeypatch.setenv("MODEL_NAME", "fake-model")
    get_settings.cache_clear()
    reset_session_store()
    init_db(tmp_path / "runtime" / "metadata.db")
    return TestClient(create_app())


def test_execute_endpoint_streams_node_events(client: TestClient) -> None:
    graph = _graph([_node("n_up")])
    save_workflow(
        Path(get_settings().APP_DATA_DIR).resolve() / "metadata.db", "s1", graph, "awaiting_approval"
    )

    resp = client.post("/api/sessions/s1/workflow/execute")
    assert resp.status_code == 200
    events = [
        json.loads(line[5:].strip())
        for block in resp.text.split("\n\n")
        for line in block.splitlines()
        if line.startswith("data:")
    ]
    types = [e["type"] for e in events]
    assert "stage_change" in types
    assert "done" in types


def test_execute_unknown_session_404s(client: TestClient) -> None:
    assert client.post("/api/sessions/nope/workflow/execute").status_code == 404


def test_pause_endpoint_unknown_session_404s(client: TestClient) -> None:
    assert client.post("/api/sessions/nope/workflow/pause").status_code == 404
