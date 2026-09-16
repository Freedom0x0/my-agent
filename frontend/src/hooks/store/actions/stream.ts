import type { Actions, WorkflowState } from "../types";

type Set = (
  partial: Partial<WorkflowState> | ((s: WorkflowState) => Partial<WorkflowState>),
) => void;
type Get = () => WorkflowState & Actions;

export function streamActions(set: Set, get: Get): Pick<Actions, "appendStream" | "finishStream" | "abortStream"> {
  return {
    appendStream: (token) => {
      set((s) => ({ streamingContent: s.streamingContent + token }));
    },
    finishStream: () => set({ streamingContent: "" }),
    abortStream: () => {
      const ctrl = get().streamController;
      ctrl?.abort();
      set({ status: "idle", streamingContent: "", streamingMessageId: null, streamController: null });
    },
  };
}
