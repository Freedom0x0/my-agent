import { useCallback } from "react";

import { api, ApiError } from "../api/httpClient";
import { mapErrorCodeToMessage, mapPlanResponse } from "../api/mappers";
import type { PlanView } from "../domain/models";

export function usePlan(
  onPlanned: (plan: PlanView) => void,
  onError: (error: { errorCode: string; message: string }) => void,
) {
  return useCallback(
    async (fileIds: string[], request: string) => {
      try {
        const response = await api.createPlan(fileIds, request);
        onPlanned(mapPlanResponse(response.plan));
      } catch (err) {
        const e = err instanceof ApiError ? err : new ApiError({
          status: 0,
          errorCode: "network_error",
          message: "规划失败",
        });
        onError({ errorCode: e.errorCode, message: mapErrorCodeToMessage(e.errorCode, e.message) });
      }
    },
    [onPlanned, onError],
  );
}