import { SIDER_MIN, SIDER_MAX, PREVIEW_MIN, PREVIEW_MAX } from "../../../domain/workflow";
import type { Actions, WorkflowState } from "../types";

type Set = (
  partial: Partial<WorkflowState> | ((s: WorkflowState) => Partial<WorkflowState>),
) => void;
type Get = () => WorkflowState & Actions;

export function panelActions(set: Set, _get: Get): Pick<Actions, "setPanelWidth" | "togglePanel"> {
  return {
    setPanelWidth: (side, width) =>
      set((s) => {
        const [min, max] = side === "sider" ? [SIDER_MIN, SIDER_MAX] : [PREVIEW_MIN, PREVIEW_MAX];
        const key = side === "sider" ? "siderWidth" : "previewWidth";
        return { panel: { ...s.panel, [key]: Math.max(min, Math.min(width, max)) } };
      }),

    togglePanel: (side) =>
      set((s) => ({
        panel: {
          ...s.panel,
          [side === "sider" ? "siderCollapsed" : "previewCollapsed"]:
            !s.panel[side === "sider" ? "siderCollapsed" : "previewCollapsed"],
        },
      })),
  };
}
