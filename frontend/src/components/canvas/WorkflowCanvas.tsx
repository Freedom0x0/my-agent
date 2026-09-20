import { useMemo } from "react";

import { STATUS_CN, layoutGraph, NODE_H, NODE_W } from "../../domain/graph";
import type { Graph, GraphLayout, GraphNode } from "../../domain/graph";
import { useAppStore } from "../../hooks/useAppStore";

/**
 * Read-only canvas: nodes laid out layer-by-column, edges drawn as SVG beziers
 * labelled with the param they feed. No drag / connect / zoom in v1 — the graph
 * is edited by talking to the model, not by hand (prd.md "不做").
 */
export function WorkflowCanvas() {
  const graph = useAppStore((s) => s.graph);
  const selectedNodeId = useAppStore((s) => s.selectedNodeId);
  const selectNode = useAppStore((s) => s.selectNode);

  const layout = useMemo(() => (graph ? layoutGraph(graph) : null), [graph]);

  if (!graph || !layout) {
    return (
      <div className="canvas-empty" data-testid="canvas-empty">
        还没有工作流图。描述你的需求，Agent 会先生成一张流程图给你确认。
      </div>
    );
  }

  return (
    <div className="canvas-wrap" data-testid="workflow-canvas">
      <div className="canvas" style={{ width: layout.width, height: layout.height }}>
        <Edges graph={graph} layout={layout} />
        {graph.nodes.map((node) => {
          const pos = layout.pos.get(node.id);
          if (!pos) return null;
          return (
            <NodeCard
              key={node.id}
              node={node}
              x={pos.x}
              y={pos.y}
              selected={node.id === selectedNodeId}
              onSelect={selectNode}
            />
          );
        })}
      </div>
    </div>
  );
}

/** A node and its edges are both stale when either endpoint is — greying only the
 *  node hides that a whole branch is dead (design.md §7 Q5). */
function isStale(graph: Graph, nodeId: string): boolean {
  return graph.nodes.find((n) => n.id === nodeId)?.status === "stale";
}

function Edges({ graph, layout }: { graph: Graph; layout: GraphLayout }) {
  return (
    <svg className="canvas-edges" width={layout.width} height={layout.height}>
      <defs>
        <marker id="graph-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
          <path className="graph-arrow" d="M0,0 L10,5 L0,10 z" />
        </marker>
        <marker id="graph-arrow-stale" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
          <path className="graph-arrow is-stale" d="M0,0 L10,5 L0,10 z" />
        </marker>
      </defs>
      {graph.edges.map((edge, i) => {
        const a = layout.pos.get(edge.from_node);
        const b = layout.pos.get(edge.to_node);
        if (!a || !b) return null;
        const x1 = a.x + NODE_W;
        const y1 = a.y + NODE_H / 2;
        const x2 = b.x;
        const y2 = b.y + NODE_H / 2;
        const stale = isStale(graph, edge.from_node) || isStale(graph, edge.to_node);
        return (
          <g
            key={`${edge.from_node}-${edge.to_node}-${edge.to_param}-${i}`}
            data-stale={stale ? "true" : "false"}
            data-testid={`graph-edge-${edge.to_node}-${edge.to_param}`}
          >
            <path
              className="graph-edge-path"
              d={`M ${x1} ${y1} C ${x1 + 55} ${y1}, ${x2 - 55} ${y2}, ${x2} ${y2}`}
              markerEnd={stale ? "url(#graph-arrow-stale)" : "url(#graph-arrow)"}
            />
            <text
              className="graph-edge-param"
              x={(x1 + x2) / 2}
              y={(y1 + y2) / 2 - 5}
              textAnchor="middle"
            >
              {edge.to_param}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function NodeCard({
  node,
  x,
  y,
  selected,
  onSelect,
}: {
  node: GraphNode;
  x: number;
  y: number;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  return (
    <div
      className={`graph-node s-${node.status}`}
      style={{ left: x, top: y }}
      role="button"
      tabIndex={0}
      aria-selected={selected}
      data-testid={`graph-node-${node.id}`}
      onClick={() => onSelect(node.id)}
      onKeyDown={(e) => {
        if (e.key !== "Enter" && e.key !== " ") return;
        e.preventDefault();
        onSelect(node.id);
      }}
    >
      <div className="graph-node-head">
        <span className="graph-seq">{node.seq}</span>
        <span className="graph-node-label" title={node.label}>{node.label}</span>
        {node.edited && <span className="graph-badge edited">已修改</span>}
        {node.status === "stale" && <span className="graph-badge stale">已作废</span>}
      </div>
      <div className="graph-node-tool">{node.tool}</div>
      <div className="graph-node-foot">
        <span className="graph-dot" />
        <span>{STATUS_CN[node.status]}</span>
        {node.cached && node.status === "ok" && <span className="graph-cached">复用</span>}
        <span className="graph-ms">{node.duration_ms ? `${node.duration_ms}ms` : ""}</span>
      </div>
    </div>
  );
}