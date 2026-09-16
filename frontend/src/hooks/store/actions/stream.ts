import type { Actions, WorkflowState } from "../types";

type Set = (
  partial: Partial<WorkflowState> | ((s: WorkflowState) => Partial<WorkflowState>),
) => void;

export function streamActions(set: Set): Pick<Actions, "appendStream" | "finishStream" | "abortStream"> {
  return {
    appendStream: (token) => {
      set((s) => ({ streamingContent: s.streamingContent + token }));
    },
    finishStream: () => set({ streamingContent: "" }),
    abortStream: () => {
      // ponytail: backend does not stream yet; stop rendering more content locally.
      // Add real abort wiring when backend ships SSE.
      set({ status: "ready", streamingContent: "" });
    },
  };
}
