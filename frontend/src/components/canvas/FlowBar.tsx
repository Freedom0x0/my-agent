import { useState } from "react";

import { useAppStore } from "../../hooks/useAppStore";

/**
 * Shared action bar above the input (both workspace tabs see it).
 *
 * 执行 approves the graph and runs it via POST /workflow/execute — the model is not
 * involved (it would only narrate). 暂停 is honest about pandas: it stops *starting*
 * nodes and the current one runs to completion, so the button stays disabled and the
 * bar says 正在完成当前节点… until the run actually settles.
 */
export function FlowBar() {
  const graph = useAppStore((s) => s.graph);
  const stage = useAppStore((s) => s.graphStage);
  const pauseRequested = useAppStore((s) => s.pauseRequested);
  const executeWorkflow = useAppStore((s) => s.executeWorkflow);
  const requestPause = useAppStore((s) => s.requestPause);
  const [showHint, setShowHint] = useState(false);

  if (!graph) return null;
  if (stage !== "awaiting_approval" && stage !== "executing" && stage !== "paused") return null;

  const executing = stage === "executing";
  const pending = graph.nodes.filter((n) => n.status === "pending").length;

  return (
    <div className="flowbar" data-testid="flowbar">
      <span className="flowbar-hint">
        {executing ? (
          <>执行中 · <b>{graph.nodes.length} 个节点</b></>
        ) : (
          <>图已生成 · <b>{graph.nodes.length} 个节点</b> · {pending} 个待执行</>
        )}
      </span>
      {executing && pauseRequested && (
        <span className="flowbar-tip" data-testid="flowbar-pausing">
          正在完成当前节点…暂停会在它跑完后生效
        </span>
      )}
      {stage === "paused" && (
        <span className="flowbar-tip" data-testid="flowbar-paused">
          已暂停 · 未完成的节点不会再启动
        </span>
      )}
      {showHint && !executing && (
        <span className="flowbar-tip" data-testid="flowbar-hint">
          哪里需要修改？在下方输入框直接说，例如「第 3 个改成按月份汇总」。
        </span>
      )}
      {executing ? (
        <button
          type="button"
          className="flow-btn"
          data-testid="flowbar-pause"
          disabled={pauseRequested}
          onClick={() => void requestPause()}
        >
          {pauseRequested ? "暂停中…" : "暂停"}
        </button>
      ) : (
        <>
          <button
            type="button"
            className="flow-btn"
            data-testid="flowbar-revise"
            onClick={() => setShowHint(true)}
          >
            修改
          </button>
          <button
            type="button"
            className="flow-btn is-primary"
            data-testid="flowbar-run"
            onClick={() => void executeWorkflow()}
          >
            {stage === "paused" ? "继续" : "执行"}
          </button>
        </>
      )}
    </div>
  );
}
