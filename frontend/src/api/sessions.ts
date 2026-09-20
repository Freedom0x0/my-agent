import {
  sessionDetailSchema,
  sessionListResponseSchema,
  workflowResponseSchema,
  type SessionDetail,
  type SessionSummary,
  type WorkflowResponse,
} from "./contracts";
import { httpClient, type RequestOptions } from "./http";

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
