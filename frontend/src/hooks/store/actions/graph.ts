import { ApiError, api } from "../../../api/httpClient";
import { makeUserFacingError, mapGraph } from "../../../api/mappers";
import type { Actions, WorkflowState } from "../types";

type Set = (
  partial: Partial<WorkflowState> | ((s: WorkflowState) => Partial<WorkflowState>),
) => void;
type Get = () => WorkflowState & Actions;

export function graphActions(
  set: Set,
  get: Get,
): Pick<
  Actions,
  | "loadWorkflow"
  | "applyGraph"
  | "setStage"
  | "clearWorkflow"
  | "selectNode"
  | "setWorkspaceView"
  | "setRightPanel"
> {
  return {
    /** Fetch the session's graph. A 404 just means "no graph yet", not an error. */
    loadWorkflow: async (sessionId) => {
      let next: Partial<WorkflowState>;
      try {
        const resp = await api.getWorkflow(sessionId);
        next = { graph: mapGraph(resp), graphStage: resp.stage };
      } catch (err) {
        next = { graph: null, graphStage: null };
        // 404 is the normal "no graph yet". Anything else is a real failure — a
        // network error, or zod rejecting the payload after a backend contract break.
        // It must not masquerade as an empty graph: the user would think their graph
        // vanished, and nothing on screen would point at the cause.
        if (!(err instanceof ApiError) || err.status !== 404) {
          next.error =
            err instanceof ApiError
              ? makeUserFacingError(err.errorCode, err.message)
              : makeUserFacingError("workflow_load_failed", String(err));
        }
      }
      // A fast session switch can land an older response after a newer one.
      if (get().currentSessionId !== sessionId) return;
      set(next);
    },

    applyGraph: (graph, stage) =>
      set((s) => ({
        graph,
        graphStage: stage ?? s.graphStage,
        // The old selection belongs to the old graph's ids.
        selectedNodeId: graph.nodes.some((n) => n.id === s.selectedNodeId)
          ? s.selectedNodeId
          : null,
      })),

    setStage: (stage) => set({ graphStage: stage }),

    clearWorkflow: () =>
      set({ graph: null, graphStage: null, selectedNodeId: null }),

    /** Clicking a node also brings its detail into the right pane (design Q3). */
    selectNode: (nodeId) => set({ selectedNodeId: nodeId, rightPanel: "node" }),

    setWorkspaceView: (view) =>
      set(view === "chat" ? { workspaceView: view, chatUnread: false } : { workspaceView: view }),

    setRightPanel: (tab) => set({ rightPanel: tab }),
  };
}