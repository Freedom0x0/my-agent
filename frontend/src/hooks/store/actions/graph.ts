import { ApiError, api, readSseStream } from "../../../api/httpClient";
import type { ExecuteEvent } from "../../../api/httpClient";
import { makeUserFacingError, mapGraph, mapStage } from "../../../api/mappers";
import type { Graph, GraphNode } from "../../../domain/graph";
import type { Actions, WorkflowState } from "../types";

type Set = (
  partial: Partial<WorkflowState> | ((s: WorkflowState) => Partial<WorkflowState>),
) => void;
type Get = () => WorkflowState & Actions;

// A run in flight that this client isn't streaming — because the page was reloaded
// mid-run — would otherwise sit on 执行中 with nothing behind it. Poll the session's
// workflow until the stage settles. One timer at a time; each tick re-checks.
const POLL_MS = 2500;
const POLL_MAX = 40; // ~100s ceiling
let workflowPoll: ReturnType<typeof setInterval> | null = null;

function stopWorkflowPoll(): void {
  if (workflowPoll !== null) {
    clearInterval(workflowPoll);
    workflowPoll = null;
  }
}

function startWorkflowPoll(sessionId: string, get: Get): void {
  if (workflowPoll !== null) return;
  let tries = 0;
  workflowPoll = setInterval(() => {
    tries += 1;
    if (tries > POLL_MAX || get().currentSessionId !== sessionId) {
      stopWorkflowPoll();
      return;
    }
    void get().loadWorkflow(sessionId);
  }, POLL_MS);
}

function patchNode(graph: Graph, nodeId: string, patch: Partial<GraphNode>): Graph {
  return { ...graph, nodes: graph.nodes.map((n) => (n.id === nodeId ? { ...n, ...patch } : n)) };
}

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
  | "executeWorkflow"
  | "requestPause"
  | "abortExecute"
  | "markNodeRunning"
  | "applyNodeEnd"
  | "refreshNodeOutputs"
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
      // Self-heal a run we can't see (reload / dropped stream); stop once it settles.
      if (next.graphStage === "executing" && !get().executeController) {
        startWorkflowPoll(sessionId, get);
      } else {
        stopWorkflowPoll();
      }
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

    /** 「执行」 — approve the graph and run it, consuming node-level SSE. */
    executeWorkflow: async () => {
      const sessionId = get().currentSessionId;
      if (!sessionId || !get().graph) return;
      if (get().graphStage === "executing") return; // already running — no double fire

      const controller = new AbortController();
      stopWorkflowPoll();
      set({ executeController: controller, pauseRequested: false, error: null });
      let sawDone = false;

      try {
        const reader = await api.executeWorkflow(sessionId, controller.signal);
        await readSseStream<ExecuteEvent>(reader, (evt) => {
          switch (evt.type) {
            case "stage_change": {
              const stage = mapStage(evt.stage);
              // The engine emits "executing" at the start and the settle stage at the
              // end; either way a pause we asked for is no longer pending.
              if (stage) set({ graphStage: stage, pauseRequested: false });
              break;
            }
            case "node_start":
              get().markNodeRunning(evt.node_id);
              break;
            case "node_end":
              get().applyNodeEnd(evt);
              // node_end carries status only — pull the finished node's artifact so the
              // detail pane shows real output mid-run, not just at the end.
              void get().refreshNodeOutputs(sessionId);
              break;
            case "done":
              sawDone = true;
              if (evt.graph) get().applyGraph(mapGraph(evt.graph), mapStage(evt.stage));
              break;
            case "error":
              set({ error: makeUserFacingError(evt.code, evt.message) });
              break;
            default:
              break;
          }
        });
      } catch (err) {
        // An abort is a session switch / unmount, not a failure — the new session owns
        // the state now, so don't paint an error into it.
        if ((err as { name?: string }).name !== "AbortError") {
          const friendly =
            err instanceof ApiError
              ? makeUserFacingError(err.errorCode, err.message)
              : makeUserFacingError("network_error", String(err));
          set({ error: friendly });
        }
      } finally {
        if (get().executeController === controller) {
          set({ executeController: null, pauseRequested: false });
        }
        // Stream ended without a terminal `done` (dropped connection): re-read the
        // authoritative stage so the UI never sits on 执行中 with no feed behind it.
        if (!sawDone && get().currentSessionId === sessionId) {
          void get().loadWorkflow(sessionId);
        }
      }
    },

    /** 「暂停」 — asks the run to stop starting nodes; the current one still finishes. */
    requestPause: async () => {
      const sessionId = get().currentSessionId;
      if (!sessionId || get().graphStage !== "executing" || get().pauseRequested) return;
      set({ pauseRequested: true });
      try {
        await api.pauseWorkflow(sessionId);
      } catch (err) {
        set({ pauseRequested: false });
        const friendly =
          err instanceof ApiError
            ? makeUserFacingError(err.errorCode, err.message)
            : makeUserFacingError("network_error", String(err));
        set({ error: friendly });
      }
    },

    abortExecute: () => {
      stopWorkflowPoll();
      get().executeController?.abort();
      set({ executeController: null, pauseRequested: false });
    },

    markNodeRunning: (nodeId) => {
      const graph = get().graph;
      if (!graph) return;
      set({ graph: patchNode(graph, nodeId, { status: "running", error: null }) });
    },

    applyNodeEnd: (e) => {
      const graph = get().graph;
      if (!graph) return;
      const prev = graph.nodes.find((n) => n.id === e.node_id);
      set({
        graph: patchNode(graph, e.node_id, {
          status: e.status,
          duration_ms: e.duration_ms ?? prev?.duration_ms ?? null,
          cached: e.cached ?? prev?.cached ?? false,
          error: e.error ?? null,
        }),
      });
    },

    refreshNodeOutputs: async (sessionId) => {
      let fetched: Graph;
      try {
        const resp = await api.getWorkflow(sessionId);
        if (get().currentSessionId !== sessionId) return;
        fetched = mapGraph(resp);
      } catch {
        return; // best-effort — the terminal `done` graph is the authoritative copy
      }
      const byId = new Map(fetched.nodes.map((n) => [n.id, n]));
      set((s) => {
        if (!s.graph) return {};
        // Take only the artifact fields: the DB keeps a currently-running node as
        // "pending" until it finishes, so a wholesale replace would regress it.
        let changed = false;
        const nodes = s.graph.nodes.map((n) => {
          const f = byId.get(n.id);
          if (!f?.output) return n;
          changed = true;
          return {
            ...n,
            output: f.output,
            duration_ms: f.duration_ms ?? n.duration_ms,
            cached: f.cached ?? n.cached,
          };
        });
        return changed ? { graph: { ...s.graph, nodes } } : {};
      });
    },
  };
}
