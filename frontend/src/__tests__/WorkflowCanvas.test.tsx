import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { FlowBar } from "../components/canvas/FlowBar";
import { NodeDetail } from "../components/canvas/NodeDetail";
import { WorkflowCanvas } from "../components/canvas/WorkflowCanvas";
import { RightPanel } from "../components/panels/RightPanel";
import { ApiError } from "../api/httpClient";
import { graphSchema, workflowResponseSchema } from "../api/contracts";
import { layoutGraph } from "../domain/graph";
import type { Graph, GraphNode, NodeStatus } from "../domain/graph";
import { useAppStore } from "../hooks/useAppStore";

const hoisted = vi.hoisted(() => ({
  chatStream: vi.fn(),
  readSseStream: vi.fn(),
  getWorkflow: vi.fn(),
  executeWorkflow: vi.fn(),
  pauseWorkflow: vi.fn(),
}));

vi.mock("../api/httpClient", async () => {
  const actual = await vi.importActual<typeof import("../api/httpClient")>(
    "../api/httpClient",
  );
  return {
    ...actual,
    api: {
      ...actual.api,
      getWorkflow: hoisted.getWorkflow,
      executeWorkflow: hoisted.executeWorkflow,
      pauseWorkflow: hoisted.pauseWorkflow,
    },
    chatStream: hoisted.chatStream,
    readSseStream: hoisted.readSseStream,
  };
});

function node(
  id: string,
  seq: number,
  label: string,
  tool: string,
  input: Record<string, unknown>,
  status: NodeStatus,
  extra: Partial<GraphNode> = {},
): GraphNode {
  return {
    id,
    seq,
    label,
    tool,
    input,
    status,
    output: null,
    duration_ms: null,
    error: null,
    edited: false,
    cached: false,
    ...extra,
  };
}

/** The prototype's 7-node graph: two sources, one fan-out (n3 → n4/n5) and a fan-in. */
function fixtureGraph(): Graph {
  return {
    nodes: [
      node("n1", 1, "读取收支明细", "tablex_upload", { file_id: "f_a", sheet: "收支明细" }, "ok", {
        cached: true,
        duration_ms: 1240,
      }),
      node("n2", 2, "读取预算表", "tablex_upload", { file_id: "f_b", sheet: "预算表" }, "ok", {
        cached: true,
      }),
      node("n3", 3, "清洗与去重", "tablex_deduplicate", { key_columns: ["订单号"], keep: "first" }, "ok"),
      node("n4", 4, "按部门汇总", "tablex_group_summary", { group_by: ["部门"] }, "pending"),
      node("n5", 5, "与预算对比", "tablex_compare", { key_columns: ["部门"] }, "stale"),
      node("n6", 6, "导出汇总结果", "tablex_export", { output_name: "部门汇总" }, "pending"),
      node("n7", 7, "导出差异报告", "tablex_export", { output_name: "预算差异" }, "pending"),
    ],
    edges: [
      { from_node: "n1", to_node: "n3", to_param: "sheet" },
      { from_node: "n3", to_node: "n4", to_param: "sheet" },
      { from_node: "n3", to_node: "n5", to_param: "left_ref" },
      { from_node: "n2", to_node: "n5", to_param: "right_ref" },
      { from_node: "n4", to_node: "n6", to_param: "sheet" },
      { from_node: "n5", to_node: "n7", to_param: "sheet" },
    ],
  };
}

/** The real action, captured before any test swaps it out for a spy. */
const realSendMessage = useAppStore.getState().sendMessage;

function seedGraph(extra: Partial<ReturnType<typeof useAppStore.getState>> = {}) {
  useAppStore.setState({
    currentSessionId: "s1",
    graph: fixtureGraph(),
    graphStage: "awaiting_approval",
    selectedNodeId: null,
    workspaceView: "canvas",
    rightPanel: "file",
    chatUnread: false,
    messages: [],
    files: [],
    executeController: null,
    pauseRequested: false,
    ...extra,
  } as Partial<ReturnType<typeof useAppStore.getState>>);
}

beforeEach(() => {
  vi.clearAllMocks();
  if (typeof window !== "undefined" && window.localStorage) window.localStorage.clear();
  hoisted.getWorkflow.mockRejectedValue(new ApiError({ status: 404, errorCode: "workflow_not_found", message: "session has no workflow" }));
  hoisted.chatStream.mockResolvedValue({} as ReadableStreamDefaultReader<Uint8Array>);
  hoisted.readSseStream.mockResolvedValue(undefined);
  hoisted.executeWorkflow.mockResolvedValue({} as ReadableStreamDefaultReader<Uint8Array>);
  hoisted.pauseWorkflow.mockResolvedValue({ session_id: "s1", stage: "executing", pause_requested: true });
  useAppStore.setState({
    currentSessionId: null,
    status: "idle",
    files: [],
    messages: [],
    graph: null,
    graphStage: null,
    selectedNodeId: null,
    workspaceView: "chat",
    rightPanel: "file",
    chatUnread: false,
    error: null,
    executeController: null,
    pauseRequested: false,
    sendMessage: realSendMessage,
  } as Partial<ReturnType<typeof useAppStore.getState>>);
});

describe("workflow contracts", () => {
  // The mocked api.getWorkflow above bypasses zod, so pin the wire shape here —
  // transcribed from backend/tests/test_e2e_mcp.py::test_e2e_workflow_route.
  const nodeDto = (id: string, label: string, seq: number) => ({
    id,
    label,
    tool: "tablex_upload",
    input: { file_id: "f_a" },
    status: "pending",
    output: null,
    duration_ms: null,
    error: null,
    edited: false,
    cached: false,
    seq,
  });

  it("parses GET /sessions/{id}/workflow", () => {
    const parsed = workflowResponseSchema.parse({
      session_id: "e2e",
      stage: "awaiting_approval",
      nodes: [nodeDto("n_up", "读取文件", 1), nodeDto("n_sum", "按部门汇总", 2)],
      edges: [{ from_node: "n_up", to_node: "n_sum", to_param: "sheet" }],
    });
    expect(parsed.nodes.map((n) => n.seq)).toEqual([1, 2]);
    expect(parsed.stage).toBe("awaiting_approval");
  });

  it("parses the graph on a done event (no session_id / stage)", () => {
    const parsed = graphSchema.parse({
      nodes: [nodeDto("n_up", "读取文件", 1), nodeDto("n_sum", "按部门汇总", 2)],
      edges: [{ from_node: "n_up", to_node: "n_sum", to_param: "sheet" }],
    });
    expect(parsed.edges).toHaveLength(1);
  });
});

describe("layoutGraph", () => {
  it("puts a node one column right of its upstream and stacks siblings by seq", () => {
    const { pos } = layoutGraph(fixtureGraph());
    // Two sources share the first column.
    expect(pos.get("n1")!.x).toBe(pos.get("n2")!.x);
    expect(pos.get("n3")!.x).toBeGreaterThan(pos.get("n1")!.x);
    // n4 and n5 both hang off n3 → same column, stacked.
    expect(pos.get("n4")!.x).toBe(pos.get("n5")!.x);
    expect(pos.get("n4")!.y).toBeLessThan(pos.get("n5")!.y);
    expect(pos.get("n6")!.x).toBeGreaterThan(pos.get("n4")!.x);
  });

  it("is deterministic for the same graph", () => {
    const a = layoutGraph(fixtureGraph());
    const b = layoutGraph(fixtureGraph());
    expect([...a.pos.entries()]).toEqual([...b.pos.entries()]);
    expect(a.width).toBe(b.width);
    expect(a.height).toBe(b.height);
  });
});

describe("WorkflowCanvas", () => {
  it("shows seq, label, tool and status for every node", () => {
    seedGraph();
    render(<WorkflowCanvas />);
    const card = screen.getByTestId("graph-node-n4");
    expect(card.textContent).toContain("4");
    expect(card.textContent).toContain("按部门汇总");
    expect(card.textContent).toContain("tablex_group_summary");
    expect(card.textContent).toContain("待执行");
    expect(card.className).toContain("s-pending");
    // 复用 marker only on a cached ok node
    expect(screen.getByTestId("graph-node-n1").textContent).toContain("复用");
    expect(card.textContent).not.toContain("复用");
  });

  it("renders a labelled edge per edge, with to_param on the line", () => {
    seedGraph();
    render(<WorkflowCanvas />);
    expect(screen.getByTestId("graph-edge-n5-left_ref").textContent).toContain("left_ref");
    expect(screen.getByTestId("graph-edge-n5-right_ref").textContent).toContain("right_ref");
    expect(screen.getByTestId("graph-edge-n4-sheet").textContent).toContain("sheet");
  });

  it("dashes the node AND its edges when the node is stale", () => {
    seedGraph();
    render(<WorkflowCanvas />);
    expect(screen.getByTestId("graph-node-n5").className).toContain("s-stale");
    expect(screen.getByTestId("graph-node-n5").textContent).toContain("已作废");
    // Both edges into the stale node are dead, not just the node itself.
    expect(screen.getByTestId("graph-edge-n5-left_ref").getAttribute("data-stale")).toBe("true");
    expect(screen.getByTestId("graph-edge-n5-right_ref").getAttribute("data-stale")).toBe("true");
    // An unrelated branch stays solid.
    expect(screen.getByTestId("graph-edge-n4-sheet").getAttribute("data-stale")).toBe("false");
  });

  it("selects a node on click and opens its detail pane", () => {
    seedGraph();
    render(<WorkflowCanvas />);
    fireEvent.click(screen.getByTestId("graph-node-n4"));
    expect(useAppStore.getState().selectedNodeId).toBe("n4");
    expect(useAppStore.getState().rightPanel).toBe("node");
    expect(screen.getByTestId("graph-node-n4").getAttribute("aria-selected")).toBe("true");
  });

  it("renders an empty state when the session has no graph", () => {
    useAppStore.setState({ graph: null });
    render(<WorkflowCanvas />);
    expect(screen.getByTestId("canvas-empty")).toBeInTheDocument();
  });
});

describe("NodeDetail", () => {
  it("renders a reference param as its upstream node, not the raw value", () => {
    seedGraph({ selectedNodeId: "n5" });
    render(<NodeDetail />);
    // n5's left_ref/right_ref come from edges — both must name their source node.
    expect(screen.getByTestId("node-ref-left_ref").textContent).toContain("第 3 个 · 清洗与去重");
    expect(screen.getByTestId("node-ref-right_ref").textContent).toContain("第 2 个 · 读取预算表");
  });

  it("ties a column param to the upstream table it binds to", () => {
    seedGraph({ selectedNodeId: "n5" });
    render(<NodeDetail />);
    const warn = screen.getByTestId("node-column-warning");
    expect(warn.textContent).toContain("key_columns");
    expect(warn.textContent).toContain("第 3 个 · 清洗与去重");
  });

  it("resolves file_id to the uploaded file name", () => {
    seedGraph({
      selectedNodeId: "n1",
      files: [
        {
          id: "f_a",
          name: "6月收支明细.xlsx",
          sizeBytes: 1,
          sheets: [],
        },
      ],
    });
    render(<NodeDetail />);
    expect(screen.getByTestId("node-file-file_id").textContent).toContain("6月收支明细.xlsx");
  });

  it("says 尚未执行 when the node has no output", () => {
    seedGraph({ selectedNodeId: "n4" });
    render(<NodeDetail />);
    expect(screen.getByTestId("node-output-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("node-error")).toBeNull();
  });

  it("renders a table output as a small table", () => {
    const graph = fixtureGraph();
    graph.nodes[4].output = {
      kind: "table",
      columns: ["部门", "差异"],
      rows: [["销售部", "-71,700"]],
    };
    seedGraph({ graph, selectedNodeId: "n5" });
    render(<NodeDetail />);
    const table = screen.getByTestId("node-output-table");
    expect(table.textContent).toContain("差异");
    expect(table.textContent).toContain("-71,700");
    expect(table.querySelectorAll("tbody tr")).toHaveLength(1);
  });

  it("renders a text output and a file output", () => {
    const graph = fixtureGraph();
    graph.nodes[3].output = { kind: "text", text: "本文档共 12 页" };
    graph.nodes[5].output = {
      kind: "file",
      ref: "outputs/n6.xlsx",
      name: "部门汇总.xlsx",
    };
    seedGraph({ graph, selectedNodeId: "n4" });
    const { rerender } = render(<NodeDetail />);
    expect(screen.getByTestId("node-output-text").textContent).toContain("本文档共 12 页");

    act(() => useAppStore.setState({ selectedNodeId: "n6" }));
    rerender(<NodeDetail />);
    const download = screen.getByTestId("node-output-file");
    expect(download.textContent).toContain("部门汇总.xlsx");
    expect(download).toHaveAttribute("href", "/api/outputs/n6");
    expect(download).toHaveAttribute("download", "部门汇总.xlsx");
  });

  it("prompts for a selection when nothing is selected", () => {
    seedGraph();
    render(<NodeDetail />);
    expect(screen.getByTestId("node-detail-empty")).toBeInTheDocument();
  });
});

describe("FlowBar (批准 / 执行 / 暂停)", () => {
  it("offers 执行 / 修改 while awaiting approval, with 执行 enabled", () => {
    seedGraph();
    render(<FlowBar />);

    expect(screen.getByTestId("flowbar").textContent).toContain("7 个节点");
    expect(screen.getByTestId("flowbar-revise")).toBeInTheDocument();
    // The engine exists now — 执行 must be clickable and must not narrate unavailability.
    expect(screen.getByTestId("flowbar-run")).not.toBeDisabled();
    expect(screen.queryByTestId("flowbar-exec-unavailable")).toBeNull();

    // 修改 points the user at the shared input rather than faking a dialog.
    expect(screen.queryByTestId("flowbar-hint")).toBeNull();
    fireEvent.click(screen.getByTestId("flowbar-revise"));
    expect(screen.getByTestId("flowbar-hint")).toBeInTheDocument();
  });

  it("swaps 执行 for 暂停 while executing, and shows the honest 正在完成 hint", () => {
    seedGraph({ graphStage: "executing" });
    const { rerender } = render(<FlowBar />);
    // No re-trigger: the run button is gone, only 暂停 remains.
    expect(screen.queryByTestId("flowbar-run")).toBeNull();
    expect(screen.getByTestId("flowbar-pause")).not.toBeDisabled();
    expect(screen.queryByTestId("flowbar-pausing")).toBeNull();

    // Once a pause is requested the current node still runs — say so, disable the button.
    act(() => useAppStore.setState({ pauseRequested: true }));
    rerender(<FlowBar />);
    expect(screen.getByTestId("flowbar-pause")).toBeDisabled();
    const hint = screen.getByTestId("flowbar-pausing").textContent ?? "";
    expect(hint).toContain("正在完成当前节点");
  });

  it("offers 继续 after a run pauses", () => {
    seedGraph({ graphStage: "paused" });
    render(<FlowBar />);
    expect(screen.getByTestId("flowbar-paused")).toBeInTheDocument();
    expect(screen.getByTestId("flowbar-run").textContent).toContain("继续");
  });

  it("stays hidden without a graph or in a drafting/revising state", () => {
    seedGraph({ graphStage: "drafting" });
    const { rerender } = render(<FlowBar />);
    expect(screen.queryByTestId("flowbar")).toBeNull();

    act(() => useAppStore.setState({ graph: null, graphStage: null }));
    rerender(<FlowBar />);
    expect(screen.queryByTestId("flowbar")).toBeNull();
  });
});

describe("workflow execution", () => {
  it("执行 calls POST /workflow/execute, not sendMessage", async () => {
    seedGraph();
    const sendMessageSpy = vi.fn();
    useAppStore.setState({ sendMessage: sendMessageSpy });
    hoisted.readSseStream.mockImplementationOnce(async () => undefined);

    await useAppStore.getState().executeWorkflow();

    expect(hoisted.executeWorkflow).toHaveBeenCalledWith("s1", expect.any(AbortSignal));
    expect(sendMessageSpy).not.toHaveBeenCalled();
    // The controller is cleared once the stream ends.
    expect(useAppStore.getState().executeController).toBeNull();
  });

  it("lights nodes up in real time from node_start / node_end", async () => {
    seedGraph();
    const seen: Array<{ status: string; ms: number | null }> = [];
    const snapshot = () => {
      const n = useAppStore.getState().graph?.nodes.find((x) => x.id === "n4");
      seen.push({ status: n?.status ?? "?", ms: n?.duration_ms ?? null });
    };
    hoisted.readSseStream.mockImplementationOnce(async (_reader, onEvent) => {
      onEvent({ type: "stage_change", stage: "executing" });
      onEvent({ type: "node_start", node_id: "n4", name: "按部门汇总" });
      snapshot();
      onEvent({ type: "node_end", node_id: "n4", status: "ok", duration_ms: 812 });
      snapshot();
    });

    await useAppStore.getState().executeWorkflow();

    expect(seen[0]).toEqual({ status: "running", ms: null });
    expect(seen[1]).toEqual({ status: "ok", ms: 812 });
  });

  it("applies the authoritative graph (with outputs) on done", async () => {
    seedGraph();
    const withOutput = fixtureGraph();
    withOutput.nodes[3].status = "ok";
    withOutput.nodes[3].output = { kind: "table", columns: ["部门"], rows: [["销售部"]] };
    hoisted.readSseStream.mockImplementationOnce(async (_reader, onEvent) => {
      onEvent({ type: "stage_change", stage: "executing" });
      onEvent({ type: "done", stage: "awaiting_approval", total_ms: 100, graph: withOutput });
    });

    await useAppStore.getState().executeWorkflow();

    const n4 = useAppStore.getState().graph?.nodes.find((n) => n.id === "n4");
    expect(n4?.output?.kind).toBe("table");
    expect(useAppStore.getState().graphStage).toBe("awaiting_approval");
  });

  it("requestPause flags the pause and calls the endpoint once", async () => {
    seedGraph({ graphStage: "executing" });
    await useAppStore.getState().requestPause();
    expect(hoisted.pauseWorkflow).toHaveBeenCalledWith("s1");
    expect(useAppStore.getState().pauseRequested).toBe(true);

    // A second click while the current node still runs must not fire again.
    await useAppStore.getState().requestPause();
    expect(hoisted.pauseWorkflow).toHaveBeenCalledTimes(1);
  });

  it("refreshes outputs without regressing an in-flight node's status", async () => {
    const graph = fixtureGraph(); // n4 pending, n5 stale
    seedGraph({ graph, graphStage: "executing" });
    // n4 is running locally; the DB still reports it as pending but now has an output.
    useAppStore.getState().markNodeRunning("n4");
    const fetched = fixtureGraph();
    fetched.nodes[3].status = "pending";
    fetched.nodes[3].output = { kind: "table", columns: ["部门"], rows: [["销售部"]] };
    hoisted.getWorkflow.mockResolvedValueOnce({
      session_id: "s1",
      stage: "executing",
      nodes: fetched.nodes,
      edges: fetched.edges,
    });

    await useAppStore.getState().refreshNodeOutputs("s1");

    const n4 = useAppStore.getState().graph?.nodes.find((n) => n.id === "n4");
    expect(n4?.status).toBe("running"); // status untouched
    expect(n4?.output?.kind).toBe("table"); // artifact picked up
  });

  it("re-reads the graph when the stream ends without a terminal done", async () => {
    seedGraph();
    hoisted.readSseStream.mockImplementationOnce(async () => undefined); // dropped
    hoisted.getWorkflow.mockResolvedValueOnce({
      session_id: "s1",
      stage: "awaiting_approval",
      nodes: fixtureGraph().nodes,
      edges: fixtureGraph().edges,
    });

    await useAppStore.getState().executeWorkflow();

    expect(hoisted.getWorkflow).toHaveBeenCalledWith("s1");
    await waitFor(() => expect(useAppStore.getState().graphStage).toBe("awaiting_approval"));
  });
});

describe("RightPanel", () => {
  it("switches between node detail and the file previewer", () => {
    seedGraph({ selectedNodeId: "n4", rightPanel: "node" });
    render(<RightPanel />);
    expect(screen.getByTestId("node-detail")).toBeInTheDocument();
    expect(screen.queryByTestId("tab-bar")).toBeNull();

    fireEvent.click(screen.getByTestId("panel-tab-file"));
    expect(useAppStore.getState().rightPanel).toBe("file");
    expect(screen.getByTestId("tab-bar")).toBeInTheDocument();
    expect(screen.queryByTestId("node-detail")).toBeNull();
  });
});

describe("graph store wiring", () => {
  it("loadWorkflow stores the graph and stage, and treats 404 as no graph", async () => {
    useAppStore.setState({ currentSessionId: "s1" });
    hoisted.getWorkflow.mockResolvedValueOnce({
      session_id: "s1",
      stage: "awaiting_approval",
      nodes: fixtureGraph().nodes,
      edges: fixtureGraph().edges,
    });

    await useAppStore.getState().loadWorkflow("s1");
    expect(useAppStore.getState().graph?.nodes).toHaveLength(7);
    expect(useAppStore.getState().graphStage).toBe("awaiting_approval");

    useAppStore.setState({ graph: null, graphStage: null });
    hoisted.getWorkflow.mockRejectedValueOnce(new ApiError({ status: 404, errorCode: "workflow_not_found", message: "session has no workflow" }));
    await useAppStore.getState().loadWorkflow("s1");
    expect(useAppStore.getState().graph).toBeNull();
    expect(useAppStore.getState().error).toBeNull();
  });

  it("surfaces a non-404 failure instead of showing an empty canvas", async () => {
    // A contract break (zod rejects the payload) or a network error must not look
    // like "no graph yet" — the user would think their graph vanished and nothing
    // on screen would point at the cause.
    useAppStore.setState({ currentSessionId: "s1", error: null });
    hoisted.getWorkflow.mockRejectedValueOnce(
      new ApiError({ status: 502, errorCode: "bad_gateway", message: "upstream down" }),
    );

    await useAppStore.getState().loadWorkflow("s1");

    expect(useAppStore.getState().graph).toBeNull();
    expect(useAppStore.getState().error?.errorCode).toBe("bad_gateway");
  });

  it("drops a stale response that lands after a session switch", async () => {
    useAppStore.setState({ currentSessionId: "s2" });
    hoisted.getWorkflow.mockResolvedValueOnce({
      session_id: "s1",
      stage: "awaiting_approval",
      nodes: fixtureGraph().nodes,
      edges: fixtureGraph().edges,
    });
    await useAppStore.getState().loadWorkflow("s1");
    expect(useAppStore.getState().graph).toBeNull();
  });

  it("takes the graph + stage off the SSE done event", async () => {
    seedGraph({ workspaceView: "chat", graph: null, graphStage: null });
    useAppStore.setState({
      files: [{ id: "f_a", name: "a.xlsx", sizeBytes: 1, sheets: [] }],
      currentSessionId: "s1",
    });
    hoisted.readSseStream.mockImplementationOnce(async (_reader, onEvent) => {
      onEvent({ type: "stage_change", stage: "awaiting_approval" });
      onEvent({
        type: "done",
        reply: "图已生成",
        tool_calls: [],
        sheets: [],
        stage: "awaiting_approval",
        graph: fixtureGraph(),
      });
    });

    await useAppStore.getState().sendMessage("做一个部门对比");

    await waitFor(() => expect(useAppStore.getState().status).toBe("completed"));
    expect(useAppStore.getState().graph?.nodes).toHaveLength(7);
    expect(useAppStore.getState().graphStage).toBe("awaiting_approval");
  });

  it("flags an unread chat dot when the model speaks while on the canvas", () => {
    useAppStore.setState({ workspaceView: "canvas" });
    useAppStore.getState().appendTextDelta("结果好了", { separate: true });
    expect(useAppStore.getState().chatUnread).toBe(true);

    useAppStore.getState().setWorkspaceView("chat");
    expect(useAppStore.getState().chatUnread).toBe(false);
  });
});
