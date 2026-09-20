import { useState } from "react";

import { useAppStore } from "../../hooks/useAppStore";

/**
 * Shared action bar above the input (both workspace tabs see it).
 *
 * 「执行」 is deliberately disabled: there is no execution engine yet, so approving a
 * graph would run nothing. Leaving it clickable invited the model to narrate a run
 * that never happened — it once named an output file that did not exist. Re-enable it
 * in `09-18-workflow-exec-engine`, together with the system prompt's §执行.
 */
export function FlowBar() {
  const graph = useAppStore((s) => s.graph);
  const stage = useAppStore((s) => s.graphStage);
  const [showHint, setShowHint] = useState(false);

  if (!graph || stage !== "awaiting_approval") return null;

  const pending = graph.nodes.filter((n) => n.status === "pending").length;

  return (
    <div className="flowbar" data-testid="flowbar">
      <span className="flowbar-hint">
        图已生成 · <b>{graph.nodes.length} 个节点</b> · {pending} 个待执行
      </span>
      <span className="flowbar-tip" data-testid="flowbar-exec-unavailable">
        执行引擎尚未实现，批准后不会有节点运行
      </span>
      {showHint && (
        <span className="flowbar-tip" data-testid="flowbar-hint">
          哪里需要修改？在下方输入框直接说，例如「第 3 个改成按月份汇总」。
        </span>
      )}
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
        disabled
        title="执行引擎尚未实现（09-18-workflow-exec-engine）"
      >
        执行
      </button>
    </div>
  );
}
