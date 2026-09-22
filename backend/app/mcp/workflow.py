"""Workflow graph model: nodes + edges + the derived topological `seq`.

The graph is the truth (design.md §3). `seq` is NOT stored — it is recomputed
from the graph every time with a deterministic algorithm, so the same graph
always numbers the same way.
"""
from __future__ import annotations

import heapq
from typing import Any

from .tools import TABLEX_TOOL_DEFINITIONS

META_TOOL_NAME = "tablex_propose_workflow"

# Session state machine (design.md §2). Only `drafting` and `awaiting_approval`
# are reachable today; the rest are owned by the execution/revise subtasks.
STAGES = ("drafting", "awaiting_approval", "executing", "paused", "revising")

NODE_STATUSES = ("pending", "running", "ok", "error", "stale")

# Every tablex_* tool except the meta tool can be a node type. The definitions
# are still sent to the model as node-type reference — they are never executed.
NODE_TOOL_NAMES = {t["name"] for t in TABLEX_TOOL_DEFINITIONS}

# name -> {param: json-schema}. Used to validate an edge's `to_param` against the
# target tool's real parameters (workflow-graph.md §4, exec-engine PRD).
TOOL_PARAMS: dict[str, dict[str, Any]] = {
    t["name"]: (t.get("input_schema") or {}).get("properties") or {}
    for t in TABLEX_TOOL_DEFINITIONS
}

# `sheet` is the universal "feed this table in" param. Every (file_id, sheet) tool
# declares it; an aggregating sink (export / export_styled / …) does not, but its
# node still needs an ordering edge that says "wire this upstream table in". Allowing
# `sheet` everywhere keeps those graphs valid while still catching misspellings like
# `sheets` — which is the whole point of the check.
UNIVERSAL_EDGE_PARAMS = frozenset({"sheet"})

# These tools can obtain their input directly from a registered file. Every
# other node consumes an upstream artifact and therefore must have an in-edge.
SOURCE_NODE_TOOL_NAMES = frozenset({
    "tablex_upload",
    "tablex_inspect",
    "tablex_read_chunk",
    "tablex_decrypt",
    "tablex_formula_graph",
    "tablex_template_fill",
})


class WorkflowError(ValueError):
    """The model submitted a graph the backend cannot accept.

    Fed back as a failed ToolResult so the model can fix it and resubmit — never
    raised out of the agent loop.
    """


PROPOSE_WORKFLOW_TOOL: dict[str, Any] = {
    "name": META_TOOL_NAME,
    "description": (
        "提交一张完整的工作流图（节点 + 边）来响应用户需求。"
        "这是唯一会被执行的动作：其余 tablex_* 工具不能直接调用，只作为节点类型的参考。"
        "调用后后端会保存图并停下，等待用户批准，不会执行任何节点。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "nodes": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "稳定节点 id（如 n_a1b2）。edges 用它引用，节点增删也不变。",
                        },
                        "label": {
                            "type": "string",
                            "description": "人能看懂、说得出口的名字（如「按部门汇总」），不要用工具名。",
                        },
                        "tool": {
                            "type": "string",
                            "description": "该节点使用的 tablex_* 工具名。",
                        },
                        "input": {
                            "type": "object",
                            "description": (
                                "工具参数。引用上游产出的参数（sheet / left_ref / right_ref / left / right）"
                                "不要写死，改用 edges 表达。上传、读文档这类源节点没有入边，参数直接给值。"
                            ),
                        },
                    },
                    "required": ["id", "label", "tool"],
                },
            },
            "edges": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "from_node": {"type": "string", "description": "上游节点 id"},
                        "to_node": {"type": "string", "description": "下游节点 id"},
                        "to_param": {
                            "type": "string",
                            "description": "这条边喂给下游的哪个参数（sheet / left_ref / right_ref …）",
                        },
                    },
                    "required": ["from_node", "to_node", "to_param"],
                },
            },
        },
        "required": ["nodes"],
    },
}


def agent_tool_definitions() -> list[dict[str, Any]]:
    """Tools sent to the model: every tablex_* node type + the one meta tool."""
    return [*TABLEX_TOOL_DEFINITIONS, PROPOSE_WORKFLOW_TOOL]


def normalize_graph(raw: Any) -> dict[str, Any]:
    """Validate a model-submitted graph and fill in the backend-owned fields.

    Raises `WorkflowError` with a message the model can act on.
    """
    if not isinstance(raw, dict):
        raise WorkflowError("参数必须是对象，形如 {nodes, edges}")

    nodes_in = raw.get("nodes")
    if not isinstance(nodes_in, list) or not nodes_in:
        raise WorkflowError("nodes 必须是非空数组")

    nodes: list[dict[str, Any]] = []
    ids: set[str] = set()
    tool_of: dict[str, str] = {}
    for item in nodes_in:
        if not isinstance(item, dict):
            raise WorkflowError("nodes 的每一项必须是对象")
        node_id = str(item.get("id") or "").strip()
        label = str(item.get("label") or "").strip()
        tool = str(item.get("tool") or "").strip()
        if not node_id:
            raise WorkflowError("节点缺少 id")
        if node_id in ids:
            raise WorkflowError(f"节点 id 重复: {node_id}")
        if not label:
            raise WorkflowError(f"节点 {node_id} 缺少 label")
        if tool not in NODE_TOOL_NAMES:
            raise WorkflowError(f"节点 {node_id} 的工具不存在: {tool or '(空)'}")
        input_dict = item.get("input") or {}
        if not isinstance(input_dict, dict):
            raise WorkflowError(f"节点 {node_id} 的 input 必须是对象")
        ids.add(node_id)
        tool_of[node_id] = tool
        nodes.append(
            {
                "id": node_id,
                "label": label,
                "tool": tool,
                "input": input_dict,
                # Backend-owned fields (UI contract, design.md §3).
                "status": "pending",
                "output": None,
                "duration_ms": None,
                "error": None,
                "edited": False,
                "cached": False,
            }
        )

    edges_in = raw.get("edges") or []
    if not isinstance(edges_in, list):
        raise WorkflowError("edges 必须是数组")

    edges: list[dict[str, str]] = []
    seen_edges: set[tuple[str, str, str]] = set()
    for item in edges_in:
        if not isinstance(item, dict):
            raise WorkflowError("edges 的每一项必须是对象")
        from_node = str(item.get("from_node") or "").strip()
        to_node = str(item.get("to_node") or "").strip()
        to_param = str(item.get("to_param") or "").strip()
        if from_node not in ids:
            raise WorkflowError(f"边的 from_node 不存在: {from_node or '(空)'}")
        if to_node not in ids:
            raise WorkflowError(f"边的 to_node 不存在: {to_node or '(空)'}")
        if not to_param:
            raise WorkflowError(f"边 {from_node}→{to_node} 缺少 to_param")
        params = TOOL_PARAMS.get(tool_of[to_node], {})
        if to_param not in params and to_param not in UNIVERSAL_EDGE_PARAMS:
            raise WorkflowError(
                f"边 {from_node}→{to_node} 的 to_param '{to_param}' 不是节点 {to_node}"
                f"（{tool_of[to_node]}）的参数；该工具的参数有: {', '.join(params) or '(无)'}"
            )
        key = (from_node, to_node, to_param)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        edges.append({"from_node": from_node, "to_node": to_node, "to_param": to_param})

    nodes_with_inbound = {edge["to_node"] for edge in edges}
    for node in nodes:
        if node["tool"] not in SOURCE_NODE_TOOL_NAMES and node["id"] not in nodes_with_inbound:
            raise WorkflowError(f"非源节点 {node['id']}（{node['tool']}）没有入边")

    graph = {"nodes": nodes, "edges": edges}
    topo_order(graph)  # raises on a cycle
    return graph


def topo_order(graph: dict[str, Any]) -> list[str]:
    """Kahn's algorithm with a stable id tie-break.

    A DAG has more than one valid topological order; the heap makes the same
    graph always yield the same one.
    """
    node_ids = [n["id"] for n in graph["nodes"]]
    indegree = {nid: 0 for nid in node_ids}
    successors: dict[str, list[str]] = {nid: [] for nid in node_ids}
    for edge in graph["edges"]:
        successors[edge["from_node"]].append(edge["to_node"])
        indegree[edge["to_node"]] += 1

    ready = [nid for nid in node_ids if indegree[nid] == 0]
    heapq.heapify(ready)
    order: list[str] = []
    while ready:
        nid = heapq.heappop(ready)
        order.append(nid)
        for nxt in successors[nid]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                heapq.heappush(ready, nxt)

    if len(order) != len(node_ids):
        raise WorkflowError("工作流图中存在环（有节点无法排进拓扑序）")
    return order


def compute_seq(graph: dict[str, Any]) -> dict[str, int]:
    """node id → display number (1-based topological position). Never stored."""
    return {nid: idx + 1 for idx, nid in enumerate(topo_order(graph))}


_STATUS_MARK = {
    "pending": "○",
    "running": "◐",
    "ok": "✓",
    "error": "✗",
    "stale": "✗ 已作废",
}


def render_graph_context(graph: dict[str, Any]) -> str:
    """The `## 当前工作流` block injected into every user turn (design.md §6)."""
    seq = compute_seq(graph)
    in_edges: dict[str, list[str]] = {}
    for edge in graph["edges"]:
        in_edges.setdefault(edge["to_node"], []).append(
            f"{seq[edge['from_node']]} → {edge['to_param']}"
        )

    lines = ["## 当前工作流"]
    for node in sorted(graph["nodes"], key=lambda n: seq[n["id"]]):
        mark = _STATUS_MARK.get(node.get("status", "pending"), "?")
        suffix = ""
        if node.get("edited"):
            suffix += "  ← 用户改过"
        if node.get("cached"):
            suffix += "  (复用)"
        lines.append(f"{seq[node['id']]}. [{node['id']}] {node['label']}  {mark}{suffix}")
        if node["id"] in in_edges:
            lines.append("   入边: " + ", ".join(in_edges[node["id"]]))
    return "\n".join(lines)


def public_graph(graph: dict[str, Any]) -> dict[str, Any]:
    """Graph shaped for the API/UI: nodes ordered by seq, each carrying its number."""
    seq = compute_seq(graph)
    nodes = [{**node, "seq": seq[node["id"]]} for node in graph["nodes"]]
    nodes.sort(key=lambda n: n["seq"])
    return {"nodes": nodes, "edges": list(graph["edges"])}


__all__ = [
    "META_TOOL_NAME",
    "NODE_STATUSES",
    "PROPOSE_WORKFLOW_TOOL",
    "STAGES",
    "TOOL_PARAMS",
    "UNIVERSAL_EDGE_PARAMS",
    "WorkflowError",
    "agent_tool_definitions",
    "compute_seq",
    "normalize_graph",
    "public_graph",
    "render_graph_context",
    "topo_order",
]
