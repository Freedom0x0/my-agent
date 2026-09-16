import {
  sessionDetailSchema,
  sessionListResponseSchema,
  type SessionDetail,
  type SessionSummary,
} from "./contracts";
import { httpClient, type RequestOptions } from "./http";

export function listSessions(
  options?: RequestOptions,
): Promise<SessionSummary[]> {
  return httpClient
    .getJson("/sessions", sessionListResponseSchema, options)
    .then((r) => r.sessions);
}

export function getSession(
  sessionId: string,
  options?: RequestOptions,
): Promise<SessionDetail> {
  return httpClient.getJson(
    `/sessions/${encodeURIComponent(sessionId)}`,
    sessionDetailSchema,
    options,
  );
}
