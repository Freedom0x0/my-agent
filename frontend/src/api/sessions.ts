import {
  pauseResponseSchema,
  sessionDetailSchema,
  sessionListResponseSchema,
  workflowResponseSchema,
  type GraphDto,
  type SessionDetail,
  type SessionSummary,
  type WorkflowResponse,
} from "./contracts";
import { httpClient, postSse, type RequestOptions } from "./http";

export function listSessions(
  options?: RequestOptions,
): Promise<SessionSummary[]> {
  return httpClient
    .getJson("/sessions", sessionListResponseSchema, options)
    .then((r) => r.sessions);
}

export type GetSessionOptions = RequestOptions & {
  limit?: number;
  beforeIndex?: number;
};

export function getSession(
  sessionId: string,
  options?: GetSessionOptions,
): Promise<SessionDetail> {
  const params: string[] = [];
  if (options?.limit != null) params.push(`limit=${options.limit}`);
  if (options?.beforeIndex != null) params.push(`before_index=${options.beforeIndex}`);
  const query = params.length ? `?${params.join("&")}` : "";
  return httpClient.getJson(
    `/sessions/${encodeURIComponent(sessionId)}${query}`,
    sessionDetailSchema,
    options,
  );
}

/** The session's workflow graph + stage. 404 (`workflow_not_found`) means the
 *  session has no graph yet — the caller treats that as "no graph", not an error. */
export function getWorkflow(
  sessionId: string,
  options?: RequestOptions,
): Promise<WorkflowResponse> {
  return httpClient.getJson(
    `/sessions/${encodeURIComponent(sessionId)}/workflow`,
    workflowResponseSchema,
    options,
  );
}

/** SSE events emitted while POST /sessions/{id}/workflow/execute runs the graph. */
export type ExecuteEvent =
  | { type: "stage_change"; stage: string }
  | { type: "node_start"; node_id: string; name: string }
  | {
      type: "node_end";
      node_id: string;
      status: "ok" | "error";
      duration_ms?: number | null;
      error?: string | null;
      cached?: boolean;
    }
  | { type: "done"; stage: string; total_ms: number; graph?: GraphDto }
  | { type: "error"; code: string; message: string };

/** Approve the graph and run it; node-level progress streams back as SSE. */
export function executeWorkflow(
  sessionId: string,
  signal?: AbortSignal,
): Promise<ReadableStreamDefaultReader<Uint8Array>> {
  return postSse(`/sessions/${encodeURIComponent(sessionId)}/workflow/execute`, {}, signal);
}

/** Ask the run to stop starting new nodes; the current one still finishes. */
export function pauseWorkflow(sessionId: string, options?: RequestOptions) {
  return httpClient.postJson(
    `/sessions/${encodeURIComponent(sessionId)}/workflow/pause`,
    {},
    pauseResponseSchema,
    options,
  );
}
