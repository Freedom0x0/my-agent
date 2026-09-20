import { Fragment } from "react";

import { COLUMN_PARAMS, firstUpstream, nodeInput, nodeRef, sourceOfParam } from "../../domain/graph";
import type { FileItem } from "../../domain/models";
import type { Graph, GraphNode } from "../../domain/graph";
import { useAppStore } from "../../hooks/useAppStore";

/**
 * Right-pane detail for the selected node. The two things it must do beyond
 * showing raw JSON:
 *
 *  - render reference params as the *upstream node's name* (never `abc::Sheet1`)
 *  - name the upstream node a column param binds to — the only defence against
 *    "upstream changed table, same column name, different meaning" silently
 *    working (prd.md §5)
 */
export function NodeDetail() {
  const graph = useAppStore((s) => s.graph);
  const selectedNodeId = useAppStore((s) => s.selectedNodeId);
  const files = useAppStore((s) => s.files);

  if (!graph) {
    return <div className="node-detail-empty" data-testid="node-detail-no-graph">还没有工作流图</div>;
  }
  const node = graph.nodes.find((n) => n.id === selectedNodeId);
  if (!node) {
    return (
      <div className="node-detail-empty" data-testid="node-detail-empty">
        点画布上的节点，查看它的输入与输出
      </div>
    );
  }

  const columnParam =
    COLUMN_PARAMS.find((p) => p in node.input) ??
    (Array.isArray(node.input.conditions) ? "conditions[].column" : null);
  const columnSource = columnParam
    ? sourceOfParam(graph, node.id, columnParam) ?? firstUpstream(graph, node.id)
    : null;

  // Edges ARE the param binding, so an in-edge names a row even when the model
  // left the referenced value out of `input`.
  const params = [...new Set([
    ...nodeInput(node).map(([key]) => key),
    ...graph.edges.filter((e) => e.to_node === node.id).map((e) => e.to_param),
  ])];

  return (
    <div className="node-detail" data-testid="node-detail">
      <div className="node-detail-head">
        <span className="graph-seq">{node.seq}</span>
        <span className="node-detail-title">{node.label}</span>
        <span className="node-detail-tool">{node.tool}</span>
      </div>

      <div className="node-sec-title">输入参数</div>
      <div className="node-params">
        {params.map((key) => (
          <Fragment key={key}>
            <div className="node-pk">{key}</div>
            <div className="node-pv">
              <ParamValue
                graph={graph}
                node={node}
                name={key}
                value={node.input[key]}
                files={files}
              />
            </div>
          </Fragment>
        ))}
      </div>

      {columnParam && columnSource && (
        <div className="node-warn" data-testid="node-column-warning">
          {columnParam} 里的列名绑定的是上游 <b>{nodeRef(columnSource)}</b> 的输出表。
          若上游换表，同名列可能语义不同。
        </div>
      )}

      {node.error && (
        <div className="node-error" data-testid="node-error">{node.error}</div>
      )}

      <div className="node-sec-title">
        输出{node.cached && node.status === "ok" ? "（复用，未重跑）" : ""}
      </div>
      <NodeOutputView node={node} />
    </div>
  );
}

function ParamValue({
  graph,
  node,
  name,
  value,
  files,
}: {
  graph: Graph;
  node: GraphNode;
  name: string;
  value: unknown;
  files: FileItem[];
}) {
  // A param fed by an edge is a reference: show where it comes from, not its id.
  const upstream = sourceOfParam(graph, node.id, name);
  if (upstream) {
    return (
      <span className="node-ref" data-testid={`node-ref-${name}`}>↑ {nodeRef(upstream)}</span>
    );
  }
  if (name === "file_id" && typeof value === "string") {
    const file = files.find((f) => f.id === value);
    return <span className="node-ref" data-testid={`node-file-${name}`}>📄 {file?.name ?? value}</span>;
  }
  if (name === "sheet" && typeof value === "string") {
    return <span className="node-ref">工作表 {value}</span>;
  }
  if (value === undefined || value === null) return null;
  if (Array.isArray(value)) {
    return (
      <>
        {value.map((v, i) => (
          <span className="node-tag" key={`${String(v)}-${i}`}>{String(v)}</span>
        ))}
      </>
    );
  }
  if (value && typeof value === "object") {
    return (
      <>
        {Object.entries(value as Record<string, unknown>).map(([k, v]) => (
          <span className="node-tag" key={k}>{k}: {String(v)}</span>
        ))}
      </>
    );
  }
  return <>{String(value)}</>;
}

function NodeOutputView({ node }: { node: GraphNode }) {
  const out = node.output;
  if (!out) {
    return <div className="node-detail-empty" data-testid="node-output-empty">尚未执行</div>;
  }
  if (out.kind === "table" && out.columns && out.rows) {
    return (
      <table className="node-output-table" data-testid="node-output-table">
        <thead>
          <tr>{out.columns.map((c) => <th key={c}>{c}</th>)}</tr>
        </thead>
        <tbody>
          {out.rows.map((row, i) => (
            <tr key={i}>{row.map((cell, j) => <td key={j}>{cell}</td>)}</tr>
          ))}
        </tbody>
      </table>
    );
  }
  if (out.kind === "text") {
    return <div className="node-output-text" data-testid="node-output-text">{out.text ?? out.ref ?? ""}</div>;
  }
  return (
    <span className="node-ref" data-testid="node-output-file">
      📄 {out.name ?? out.ref ?? out.kind}
    </span>
  );
}