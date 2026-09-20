"""DAG execution engine — run an approved workflow graph in topological order.

The graph is the truth (design.md §1); execution is its deterministic derivation.
Two constraints drive the whole design (exec-engine PRD 关键约束):

1. Handlers read their data from `session.tables[(file_id, sheet)]`, but a graph
   edge says "this param comes from that node". `_bind_inputs` translates one into
   the other by materializing the upstream output into a synthetic `(file_id, sheet)`
   slot and binding the param to it.
2. Handlers mutate `session.tables` in place. Running two fan-out branches against
   one shared dict would let the first branch corrupt the second *silently*, so
   every node runs against its own `_NodeSession` seeded from the upstream
   artifacts on disk.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any, AsyncIterator, Callable

import pandas as pd

from ..config import get_settings
from .handlers import HANDLERS
from .schemas import ToolCall, ToolResult
from .session import Session
from .workflow import TOOL_PARAMS, WorkflowError, public_graph, topo_order

logger = logging.getLogger(__name__)

# ponytail: threads, not processes. pandas/openpyxl hold the GIL, so fan-out is
# overlapped rather than truly parallel; a process pool needs Session to be
# picklable, which is its own task (design.md §9).
MAX_NODE_WORKERS = 4
_PREVIEW_ROWS = 20
_PREVIEW_COLS = 20

NodeRunner = Callable[[ToolCall, Any], ToolResult]


# ----- artifact storage ---------------------------------------------------


def _nodes_dir(session_id: str) -> Path:
    base = Path(get_settings().APP_DATA_DIR).resolve()
    path = base / "sessions" / session_id / "nodes"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _rel_ref(session_id: str, filename: str) -> str:
    return f"sessions/{session_id}/nodes/{filename}"


def _abs_ref(ref: str) -> Path:
    return Path(get_settings().APP_DATA_DIR).resolve() / ref


def _write_table(df: pd.DataFrame, session_id: str, node_id: str) -> str:
    """Persist a node's table output; return the ref stored on the node.

    Prefers parquet (the contract path, workflow-graph.md §7), falling back to
    pickle when no parquet engine is installed — `_read_table` reads either back.
    """
    path = _nodes_dir(session_id) / f"{node_id}.parquet"
    try:
        df.to_parquet(path)
    except Exception:
        path = _nodes_dir(session_id) / f"{node_id}.pkl"
        df.to_pickle(path)
    return _rel_ref(session_id, path.name)


def _read_table(ref: str) -> pd.DataFrame:
    path = _abs_ref(ref)
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    return pd.read_pickle(path)


def _write_text(text: str, session_id: str, node_id: str) -> str:
    path = _nodes_dir(session_id) / f"{node_id}.txt"
    path.write_text(text, encoding="utf-8")
    return _rel_ref(session_id, path.name)


# ----- per-node isolation -------------------------------------------------


class _NodeSession:
    """A node's isolated view: its own `tables`, shared `files`/`output_dir`.

    Sharing the real `session.tables` is exactly the fan-out bug: branch A mutates
    the upstream sheet, branch B then reads a different table than it was promised.
    A fresh dict per node makes each branch seed from the same artifact and diverge
    only in its own copy.
    """

    def __init__(self, base: Session, tables: dict[str, pd.DataFrame], node_id: str):
        self.files = base.files
        self.tables = tables
        self.output_dir = base.output_dir
        self.audit_events: list[Any] = []
        self.tool_calls_log: list[Any] = []
        self.request_id = base.request_id
        # Side-effect id derived from the node: re-running overwrites, not piles up.
        self.node_output_id = node_id
        self.output_id: str | None = None
        self.output_path: str | None = None

    def has_file(self, file_id: str) -> bool:
        return file_id in self.files

    def touch(self) -> None:
        pass

    def is_expired(self) -> bool:
        return False


def _virtual_ref(node: dict[str, Any]) -> tuple[str, str]:
    """The synthetic `(file_id, sheet)` slot an upstream node's table lands in.

    The sheet half uses the node's label so a downstream export writes a readable
    sheet name instead of an internal id.
    """
    return f"wf_{node['id']}", (node.get("label") or "输出")


def _bind_inputs(
    graph: dict[str, Any], node: dict[str, Any], tables: dict[str, pd.DataFrame]
) -> tuple[dict[str, Any], list[str]]:
    """Materialize in-edge upstream outputs into `tables`; bind them to params.

    Binding is by param shape: `sheet` is the `(file_id, sheet)` pair, a param whose
    schema is an object gets `{file_id, sheet}` (join's `left`/`right`), anything
    else gets the raw table ref (compare's `left_ref`/`right_ref`).
    """
    nodes_by_id = {n["id"]: n for n in graph["nodes"]}
    bound: dict[str, Any] = dict(node.get("input") or {})
    props = TOOL_PARAMS.get(node["tool"], {})
    errors: list[str] = []

    for edge in graph["edges"]:
        if edge["to_node"] != node["id"]:
            continue
        upstream = nodes_by_id[edge["from_node"]]
        output = upstream.get("output") or {}
        if output.get("kind") != "table" or not output.get("ref"):
            errors.append(f"上游节点 {upstream['id']} 没有表格输出可供绑定")
            continue
        vfid, vsheet = _virtual_ref(upstream)
        key = f"{vfid}::{vsheet}"
        tables[key] = _read_table(output["ref"])
        param = edge["to_param"]
        prop = props.get(param)
        if param == "sheet":
            bound["file_id"], bound["sheet"] = vfid, vsheet
        elif isinstance(prop, dict) and prop.get("type") == "object":
            bound[param] = {"file_id": vfid, "sheet": vsheet}
        else:
            bound[param] = key
    return bound, errors


# ----- output extraction --------------------------------------------------


def _table_artifact(df: pd.DataFrame, session_id: str, node_id: str) -> dict[str, Any]:
    ref = _write_table(df, session_id, node_id)
    capped = df.iloc[:, :_PREVIEW_COLS]
    return {
        "kind": "table",
        "ref": ref,
        "row_count": int(len(df)),
        "columns": [str(c) for c in capped.columns],
        "rows": capped.head(_PREVIEW_ROWS).astype(str).values.tolist(),
    }


def _build_output(
    session_id: str,
    node_id: str,
    bound: dict[str, Any],
    tables: dict[str, pd.DataFrame],
    result: ToolResult,
) -> dict[str, Any]:
    """Turn a handler result into the node's `output` artifact.

    Handlers return their product in `data` under known keys; when none matches we
    fall back to the sheet the node was bound to (in-place transform tools), then to
    a text artifact (inspect/analyze — they produce a report, not a table).
    """
    data = result.data or {}

    output_id = data.get("output_id")
    if output_id:
        return {
            "kind": "file",
            "ref": f"outputs/{output_id}.xlsx",
            "name": data.get("output_name"),
        }

    sheet = data.get("output_sheet")
    if isinstance(sheet, str) and sheet in tables:
        return _table_artifact(tables[sheet], session_id, node_id)

    sheets = data.get("sheets")
    if isinstance(sheets, list) and sheets and isinstance(sheets[0], str) and sheets[0] in tables:
        return _table_artifact(tables[sheets[0]], session_id, node_id)

    refs = data.get("loaded_refs")
    if isinstance(refs, list) and refs:
        for key in refs:
            if key in tables:
                return _table_artifact(tables[key], session_id, node_id)

    fid, sh = bound.get("file_id"), bound.get("sheet")
    if fid and sh and f"{fid}::{sh}" in tables:
        return _table_artifact(tables[f"{fid}::{sh}"], session_id, node_id)

    text = result.summary
    if data:
        text += "\n" + json.dumps(data, ensure_ascii=False, default=str)
    return {"kind": "text", "ref": _write_text(text, session_id, node_id), "text": text[:2000]}


# ----- node execution -----------------------------------------------------


def _node_fields(
    status: str, duration_ms: int | None, *, output: Any = None, error: str | None = None
) -> dict[str, Any]:
    return {
        "status": status,
        "output": output,
        "duration_ms": duration_ms,
        "error": error,
        "cached": False,
    }


def _run_node(
    session: Session,
    node: dict[str, Any],
    graph: dict[str, Any],
    node_runner: NodeRunner | None,
) -> dict[str, Any]:
    """Run one node against an isolated session; return its new node fields."""
    started = time.perf_counter()
    tables: dict[str, pd.DataFrame] = {}
    bound, bind_errors = _bind_inputs(graph, node, tables)
    if bind_errors:
        return _node_fields(
            "error", int((time.perf_counter() - started) * 1000), error="；".join(bind_errors)
        )

    shim = _NodeSession(session, tables, node["id"])
    tool_call = ToolCall(tool_use_id=node["id"], name=node["tool"], input=bound)
    try:
        if node_runner is not None:
            result = node_runner(tool_call, shim)
        else:
            spec = HANDLERS.get(node["tool"])
            if spec is None:
                raise WorkflowError(f"未知工具: {node['tool']}")
            result = spec.fn(tool_call, shim)
    except Exception as exc:  # handlers must not raise; defensive per handlers.md
        logger.exception("node %s (%s) crashed", node["id"], node["tool"])
        result = ToolResult(success=False, summary="节点执行异常", error=str(exc)[:300])

    duration_ms = int((time.perf_counter() - started) * 1000)
    if not result.success:
        return _node_fields("error", duration_ms, error=result.error or result.summary)
    try:
        output = _build_output(session.session_id, node["id"], bound, tables, result)
    except Exception as exc:  # artifact write failure is a node failure, not a crash
        logger.exception("node %s output write failed", node["id"])
        return _node_fields("error", duration_ms, error=f"输出落盘失败: {exc}"[:300])
    return _node_fields("ok", duration_ms, output=output)


# ----- invalidation & reuse ----------------------------------------------


def transitive_downstream(graph: dict[str, Any], node_id: str) -> set[str]:
    """Every node reachable from `node_id` (excluding `node_id` itself)."""
    successors: dict[str, list[str]] = {}
    for edge in graph["edges"]:
        successors.setdefault(edge["from_node"], []).append(edge["to_node"])
    seen: set[str] = set()
    stack = list(successors.get(node_id, []))
    while stack:
        nid = stack.pop()
        if nid in seen:
            continue
        seen.add(nid)
        stack.extend(successors.get(nid, []))
    return seen


def mark_stale(graph: dict[str, Any], node_id: str) -> list[str]:
    """Invalidate `node_id`'s transitive downstream (not the node itself).

    Branches that don't descend from the edited node are untouched, so a later run
    reuses their outputs (partial recompute, design.md §4).
    """
    affected = transitive_downstream(graph, node_id)
    for node in graph["nodes"]:
        if node["id"] in affected:
            node["status"] = "stale"
            node["cached"] = False
    return sorted(affected)


def _is_reusable(node: dict[str, Any]) -> bool:
    if node.get("status") != "ok":
        return False
    output = node.get("output") or {}
    if not output.get("ref"):
        return False
    if output.get("kind") == "table":
        return _abs_ref(output["ref"]).exists()
    return True


# ----- scheduler ----------------------------------------------------------


def _execute_sync(
    session: Session,
    *,
    store: Any,
    emit: Callable[[dict[str, Any]], None],
    node_runner: NodeRunner | None = None,
    max_workers: int = MAX_NODE_WORKERS,
) -> None:
    """Walk the graph in topological order, running ready nodes on a thread pool.

    Readiness = every in-edge source is `ok`; `ok` nodes with an on-disk artifact are
    reused, not re-run. Pause stops *starting* nodes — a running node finishes.
    """
    graph = session.graph
    if not graph or not graph.get("nodes"):
        raise WorkflowError("会话还没有工作流图，无法执行")

    nodes = {n["id"]: n for n in graph["nodes"]}
    order = topo_order(graph)
    preds: dict[str, list[str]] = {nid: [] for nid in nodes}
    for edge in graph["edges"]:
        preds[edge["to_node"]].append(edge["from_node"])

    session.pause_requested = False
    session.stage = "executing"
    if store is not None:
        store.persist_workflow(session)
    emit({"type": "stage_change", "stage": "executing"})

    status: dict[str, str] = {}
    to_run: set[str] = set()
    for nid in order:
        node = nodes[nid]
        if _is_reusable(node):
            node["cached"] = True
            status[nid] = "ok"
            emit({"type": "node_end", "node_id": nid, "status": "ok",
                  "duration_ms": 0, "cached": True})
            continue
        node.update({"status": "pending", "cached": False, "error": None, "output": None})
        status[nid] = "pending"
        to_run.add(nid)

    graph_started = time.perf_counter()
    running: dict[Future, str] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        while to_run or running:
            if not session.pause_requested:
                for nid in order:
                    if nid in to_run and all(status[p] == "ok" for p in preds[nid]):
                        to_run.discard(nid)
                        status[nid] = "running"
                        nodes[nid]["status"] = "running"
                        emit({"type": "node_start", "node_id": nid, "name": nodes[nid]["label"]})
                        running[pool.submit(_run_node, session, nodes[nid], graph, node_runner)] = nid
            if not running:
                break  # paused, or every remaining node is blocked upstream

            done, _ = wait(list(running), return_when=FIRST_COMPLETED)
            for future in done:
                nid = running.pop(future)
                try:
                    fields = future.result()
                except Exception as exc:  # pragma: no cover - defensive
                    fields = _node_fields("error", None, error=str(exc)[:300])
                nodes[nid].update(fields)
                status[nid] = fields["status"]
                emit({"type": "node_end", "node_id": nid, "status": fields["status"],
                      "duration_ms": fields.get("duration_ms"), "error": fields.get("error")})
                if store is not None:
                    store.persist_workflow(session)

                if fields["status"] != "ok":
                    reason = f"上游节点 {nid} 执行失败"
                    for downstream in transitive_downstream(graph, nid):
                        if status.get(downstream) == "pending":
                            to_run.discard(downstream)
                            status[downstream] = "error"
                            nodes[downstream].update(
                                {"status": "error", "error": reason, "duration_ms": None}
                            )
                            emit({"type": "node_end", "node_id": downstream, "status": "error",
                                  "duration_ms": None, "error": reason})

    total_ms = int((time.perf_counter() - graph_started) * 1000)
    session.stage = "paused" if session.pause_requested else "awaiting_approval"
    session.pause_requested = False
    if store is not None:
        store.persist_workflow(session)
    emit({"type": "stage_change", "stage": session.stage})
    emit({"type": "done", "stage": session.stage, "total_ms": total_ms,
          "graph": public_graph(session.graph)})


async def execute_graph_stream(
    session: Session,
    *,
    store: Any,
    node_runner: NodeRunner | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Async SSE view of `_execute_sync`.

    The scheduler is blocking (it waits on a thread pool), so it runs in its own
    thread and hands events back through an asyncio queue.
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def emit(event: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    def run() -> None:
        try:
            _execute_sync(session, store=store, emit=emit, node_runner=node_runner)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("execution engine crashed")
            emit({"type": "error", "code": "execution_failed", "message": str(exc)[:300]})
        finally:
            emit({"_end": True})

    threading.Thread(target=run, daemon=True).start()
    while True:
        event = await queue.get()
        if event.pop("_end", False):
            break
        yield event


__all__ = [
    "MAX_NODE_WORKERS",
    "execute_graph_stream",
    "mark_stale",
    "transitive_downstream",
]
