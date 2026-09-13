import { useCallback } from "react";

import { api, ApiError } from "../api/httpClient";
import { mapErrorCodeToMessage, mapExecutionResponse } from "../api/mappers";
import type { ExecutionView } from "../domain/models";

export function useExecution(
  onExecuted: (result: ExecutionView) => void,
  onError: (error: { errorCode: string; message: string }) => void,
) {
  return useCallback(
    async (fileIds: string[], plan: unknown, confirmationToken: string | null) => {
      try {
        const response = await api.executePlan(fileIds, plan, confirmationToken);
        onExecuted(mapExecutionResponse(response));
      } catch (err) {
        const e = err instanceof ApiError ? err : new ApiError({
          status: 0,
          errorCode: "network_error",
          message: "执行失败",
        });
        onError({ errorCode: e.errorCode, message: mapErrorCodeToMessage(e.errorCode, e.message) });
      }
    },
    [onExecuted, onError],
  );
}