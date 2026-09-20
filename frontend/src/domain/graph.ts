/**
 * Workflow graph — the frontend's read-only view of the backend graph model.
 *
 * Field names stay snake_case on purpose: the graph is a backend contract the UI
 * only renders (workflow-graph.md §3), so renaming `from_node`/`duration_ms` here
 * would just add a mapping layer with no consumer.
 */

export type NodeStatus = "pending" | "running" | "ok" | "error" | "stale";

export type Stage =
  | "drafting"
  | "awaiting_approval"
  | "executing"
  | "paused"
  | "revising";

/** Node output artifact (design.md §5). `columns`/`rows`/`text` are only present
 *  when the backend can inline a small preview; `ref` is the on-disk artifact. */
export type NodeOutput = {
  kind: string;
  ref?: string | null;
  name?: string | null;
  text?: string | null;
  columns?: string[] | null;
  rows?: string[][] | null;
};

export type GraphNode = {
  id: string;
  label: string;
  tool: string;
  input: Record<string, unknown>;
  status: NodeStatus;
  output: NodeOutput | null;
  duration_ms?: number | null;
  error?: string | null;
  edited?: boolean;
  cached?: boolean;
  /** Derived topological number, computed by the backend. Never recomputed here. */
  seq: number;
};

export type GraphEdge = {
  from_node: string;
  to_node: string;
  to_param: string;
};

export type Graph = {
  nodes: GraphNode[];
  edges: GraphEdge[];
};

export const STATUS_CN: Record<NodeStatus, string> = {
  pending: "待执行",
  running: "执行中",
  ok: "成功",
  error: "失败",
  stale: "已作废",
};

/** Params whose value is a column name of the upstream table — see design.md §3. */
export const COLUMN_PARAMS = ["key_columns", "group_by"] as const;

export function nodeInput(node: GraphNode): [string, unknown][] {
  return Object.entries(node.input ?? {});
}

/** Which param of `nodeId` this edge feeds — edges ARE the param binding. */
export function sourceOfParam(
  graph: Graph,
  nodeId: string,
  param: string,
): GraphNode | null {
  const edge = graph.edges.find((e) => e.to_node === nodeId && e.to_param === param);
  if (!edge) return null;
  return graph.nodes.find((n) => n.id === edge.from_node) ?? null;
}

export function firstUpstream(graph: Graph, nodeId: string): GraphNode | null {
  const edge = graph.edges.find((e) => e.to_node === nodeId);
  if (!edge) return null;
  return graph.nodes.find((n) => n.id === edge.from_node) ?? null;
}

/** "第 3 个 · 清洗与去重" — the user's only way to name a node. */
export function nodeRef(node: GraphNode): string {
  return `第 ${node.seq} 个 · ${node.label}`;
}

// Mirrors .graph-node { width; height } in styles.css — the edges anchor on these.
export const NODE_W = 176;
export const NODE_H = 78;
const GAP_X = 58;
const GAP_Y = 30;
const PAD = 26;

export type GraphLayout = {
  pos: Map<string, { x: number; y: number }>;
  width: number;
  height: number;
};

/**
 * Layer-by-column layout: node level = longest path from a source, rows filled in
 * seq order. Unglamorous, but v1 is read-only (no drag, no connect, no minimap),
 * which is everything React Flow would have brought — and it doesn't do DAG
 * layout anyway (that's dagre). ~30 lines beats a dependency here.
 */
export function layoutGraph(graph: Graph): GraphLayout {
  const sorted = [...graph.nodes].sort((a, b) => a.seq - b.seq);
  const level = new Map<string, number>();

  for (const node of sorted) {
    const incoming = graph.edges.filter((e) => e.to_node === node.id);
    const from = incoming
      .map((e) => level.get(e.from_node))
      .filter((l): l is number => l !== undefined);
    level.set(node.id, from.length ? Math.max(...from) + 1 : 0);
  }

  const rowsUsed = new Map<number, number>();
  const pos = new Map<string, { x: number; y: number }>();
  for (const node of sorted) {
    const lv = level.get(node.id) ?? 0;
    const row = rowsUsed.get(lv) ?? 0;
    rowsUsed.set(lv, row + 1);
    pos.set(node.id, {
      x: PAD + lv * (NODE_W + GAP_X),
      y: PAD + row * (NODE_H + GAP_Y),
    });
  }

  const maxLevel = Math.max(0, ...level.values());
  const maxRow = Math.max(0, ...[...rowsUsed.values()].map((n) => n - 1));
  return {
    pos,
    width: PAD * 2 + (maxLevel + 1) * NODE_W + maxLevel * GAP_X,
    height: PAD * 2 + (maxRow + 1) * NODE_H + maxRow * GAP_Y,
  };
}