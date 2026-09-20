"""Unit tests for the workflow graph model (mcp/workflow.py)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from backend.app.db import get_workflow, init_db, save_workflow
from backend.app.mcp.session import SessionStore
from backend.app.mcp.workflow import (
    META_TOOL_NAME,
    WorkflowError,
    agent_tool_definitions,
    compute_seq,
    normalize_graph,
    public_graph,
    render_graph_context,
    topo_order,
)


def _graph(nodes: list[dict[str, Any]] | None = None, edges: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """A fan-out / fan-in graph: 上传 → 汇总, 上传 → 明细, both → 导出."""
    if nodes is None:
        nodes = [
            {"id": "n_up", "label": "读取收支明细", "tool": "tablex_upload", "input": {"file_id": "f1"}},
            {"id": "n_sum", "label": "按部门汇总", "tool": "tablex_group_summary", "input": {"group_by": ["部门"]}},
            {"id": "n_det", "label": "筛出研发", "tool": "tablex_filter", "input": {}},
            {"id": "n_out", "label": "导出结果", "tool": "tablex_export", "input": {"output_name": "结果"}},
        ]
    if edges is None:
        edges = [
            {"from_node": "n_up", "to_node": "n_sum", "to_param": "sheet"},
            {"from_node": "n_up", "to_node": "n_det", "to_param": "sheet"},
            {"from_node": "n_sum", "to_node": "n_out", "to_param": "sheet"},
            {"from_node": "n_det", "to_node": "n_out", "to_param": "sheet"},
        ]
    return normalize_graph({"nodes": nodes, "edges": edges})


# ----- normalize_graph -----


def test_normalize_fills_backend_owned_fields() -> None:
    graph = _graph()
    node = graph["nodes"][0]
    assert node["id"] == "n_up"
    assert node["status"] == "pending"
    assert node["output"] is None
    assert node["duration_ms"] is None
    assert node["error"] is None
    assert node["edited"] is False
    assert node["cached"] is False


def test_normalize_drops_duplicate_edges() -> None:
    graph = _graph(edges=[
        {"from_node": "n_up", "to_node": "n_sum", "to_param": "sheet"},
        {"from_node": "n_up", "to_node": "n_sum", "to_param": "sheet"},
    ])
    assert len(graph["edges"]) == 1


@pytest.mark.parametrize(
    "nodes, edges, message",
    [
        ([], [], "nodes 必须是非空数组"),
        ([{"label": "x", "tool": "tablex_upload"}], [], "id"),
        ([{"id": "n1", "tool": "tablex_upload"}], [], "label"),
        ([{"id": "n1", "label": "x", "tool": "tablex_nope"}], [], "工具不存在"),
        (
            [{"id": "n1", "label": "a", "tool": "tablex_upload"}, {"id": "n1", "label": "b", "tool": "tablex_upload"}],
            [],
            "重复",
        ),
        (
            [{"id": "n1", "label": "a", "tool": "tablex_upload"}],
            [{"from_node": "n1", "to_node": "n2", "to_param": "sheet"}],
            "to_node 不存在",
        ),
        (
            [{"id": "n1", "label": "a", "tool": "tablex_upload"}],
            [{"from_node": "n1", "to_node": "n1", "to_param": "sheet"}],
            "环",
        ),
    ],
)
def test_normalize_rejects_bad_graphs(nodes: Any, edges: Any, message: str) -> None:
    with pytest.raises(WorkflowError) as exc_info:
        normalize_graph({"nodes": nodes, "edges": edges})
    assert message in str(exc_info.value)


def test_normalize_rejects_cycle() -> None:
    with pytest.raises(WorkflowError):
        _graph(
            edges=[
                {"from_node": "n_up", "to_node": "n_sum", "to_param": "sheet"},
                {"from_node": "n_sum", "to_node": "n_up", "to_param": "sheet"},
            ]
        )


# ----- seq: derived, deterministic -----


def test_seq_is_topological_and_starts_at_one() -> None:
    graph = _graph()
    seq = compute_seq(graph)
    assert sorted(seq.values()) == [1, 2, 3, 4]
    assert seq["n_up"] == 1
    assert seq["n_out"] == 4


def test_seq_is_deterministic_for_the_same_graph() -> None:
    graph = _graph()
    first = compute_seq(graph)
    for _ in range(5):
        assert compute_seq(graph) == first


def test_seq_tie_break_is_by_node_id_not_insertion_order() -> None:
    """Two ready nodes at the same level must order by id, not by list position."""
    forward = _graph(nodes=[
        {"id": "n_a", "label": "a", "tool": "tablex_upload", "input": {}},
        {"id": "n_b", "label": "b", "tool": "tablex_upload", "input": {}},
    ], edges=[])
    backward = _graph(nodes=[
        {"id": "n_b", "label": "b", "tool": "tablex_upload", "input": {}},
        {"id": "n_a", "label": "a", "tool": "tablex_upload", "input": {}},
    ], edges=[])
    assert compute_seq(forward) == {"n_a": 1, "n_b": 2}
    assert compute_seq(backward) == {"n_a": 1, "n_b": 2}


def test_topo_order_lists_every_node_once() -> None:
    order = topo_order(_graph())
    assert sorted(order) == ["n_det", "n_out", "n_sum", "n_up"]


def test_seq_is_not_stored_on_the_node() -> None:
    graph = _graph()
    assert all("seq" not in node for node in graph["nodes"])


def test_public_graph_adds_seq_without_mutating_the_stored_graph() -> None:
    graph = _graph()
    public = public_graph(graph)
    assert [n["id"] for n in public["nodes"]] == ["n_up", "n_det", "n_sum", "n_out"]
    assert public["nodes"][0]["seq"] == 1
    assert all("seq" not in node for node in graph["nodes"])


# ----- model-facing rendering -----


def test_render_graph_context_lists_seq_label_status_and_in_edges() -> None:
    graph = _graph()
    by_id = {n["id"]: n for n in graph["nodes"]}
    by_id["n_sum"]["status"] = "ok"
    by_id["n_sum"]["edited"] = True
    by_id["n_det"]["status"] = "stale"
    lines = render_graph_context(graph).splitlines()
    assert lines[0] == "## 当前工作流"
    assert "1. [n_up] 读取收支明细  ○" in lines
    assert "2. [n_det] 筛出研发  ✗ 已作废" in lines
    assert "3. [n_sum] 按部门汇总  ✓  ← 用户改过" in lines
    assert "4. [n_out] 导出结果  ○" in lines
    assert "   入边: 1 → sheet" in lines


def test_render_graph_context_shows_fan_in() -> None:
    text = render_graph_context(_graph())
    # 导出吃两条入边，各带自己的 to_param（依赖 + 参数绑定是同一件事）。
    assert "入边: 3 → sheet, 2 → sheet" in text


# ----- the meta tool -----


def test_meta_tool_is_the_only_extra_definition() -> None:
    tools = agent_tool_definitions()
    assert tools[-1]["name"] == META_TOOL_NAME
    names = [t["name"] for t in tools]
    assert len(names) == len(set(names))
    # Every node-type definition is still sent to the model untouched.
    assert "tablex_export" in names
    assert "tablex_group_summary" in names


def test_meta_tool_schema_requires_nodes() -> None:
    tool = agent_tool_definitions()[-1]
    assert tool["input_schema"]["required"] == ["nodes"]
    assert "edges" in tool["input_schema"]["properties"]


# ----- persistence -----


def test_workflow_round_trips_through_sqlite(tmp_path: Path) -> None:
    db_path = tmp_path / "metadata.db"
    init_db(db_path)
    graph = _graph()

    save_workflow(db_path, "s1", graph, "awaiting_approval")
    saved = get_workflow(db_path, "s1")
    assert saved is not None
    assert saved["stage"] == "awaiting_approval"
    assert [n["id"] for n in saved["graph"]["nodes"]] == ["n_up", "n_sum", "n_det", "n_out"]

    # Upsert, not insert: a resubmitted graph replaces the old one.
    save_workflow(db_path, "s1", _graph(nodes=[{"id": "n_x", "label": "x", "tool": "tablex_upload"}], edges=[]), "drafting")
    saved = get_workflow(db_path, "s1")
    assert saved is not None
    assert [n["id"] for n in saved["graph"]["nodes"]] == ["n_x"]


def test_get_workflow_returns_none_for_unknown_session(tmp_path: Path) -> None:
    db_path = tmp_path / "metadata.db"
    init_db(db_path)
    assert get_workflow(db_path, "nope") is None


def test_store_rehydrates_graph_after_eviction(tmp_path: Path) -> None:
    db_path = tmp_path / "metadata.db"
    init_db(db_path)
    store = SessionStore(tmp_path / "out", db_path=db_path)
    session = store.get_or_create("sid")
    session.graph = _graph()
    session.stage = "awaiting_approval"
    store.persist_workflow(session)

    # A fresh store (process restart) must reload the graph from SQLite.
    fresh = SessionStore(tmp_path / "out", db_path=db_path).get_or_create("sid")
    assert fresh.stage == "awaiting_approval"
    assert fresh.graph is not None
    assert compute_seq(fresh.graph)["n_up"] == 1


def test_persist_workflow_is_noop_without_graph(tmp_path: Path) -> None:
    db_path = tmp_path / "metadata.db"
    init_db(db_path)
    store = SessionStore(tmp_path / "out", db_path=db_path)
    session = store.get_or_create("sid")
    store.persist_workflow(session)  # must not raise, must not create a row
    assert get_workflow(db_path, "sid") is None