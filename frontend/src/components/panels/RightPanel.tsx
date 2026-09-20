import { useAppStore } from "../../hooks/useAppStore";
import { NodeDetail } from "../canvas/NodeDetail";
import { Previewer } from "../Previewer";

/**
 * Right pane, now two tabs: node detail (canvas) and the existing file/output
 * previewer. Selecting a node switches here automatically (design.md §7 Q3).
 */
export function RightPanel() {
  const tab = useAppStore((s) => s.rightPanel);
  const setRightPanel = useAppStore((s) => s.setRightPanel);

  return (
    <div className="right-panel">
      <div className="viewtabs panel-tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "node"}
          className={`vtab ${tab === "node" ? "is-active" : ""}`}
          data-testid="panel-tab-node"
          onClick={() => setRightPanel("node")}
        >
          节点详情
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "file"}
          className={`vtab ${tab === "file" ? "is-active" : ""}`}
          data-testid="panel-tab-file"
          onClick={() => setRightPanel("file")}
        >
          文件预览
        </button>
      </div>
      <div className="right-panel-body">
        {tab === "node" ? <NodeDetail /> : <Previewer />}
      </div>
    </div>
  );
}