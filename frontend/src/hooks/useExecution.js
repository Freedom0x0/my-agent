import { useCallback } from "react";
import { api, ApiError } from "../api/httpClient";
import { mapErrorCodeToMessage, mapExecutionResponse } from "../api/mappers";
export function useExecution(onExecuted, onError) {
    return useCallback(async (fileIds, plan, confirmationToken) => {
        try {
            const response = await api.executePlan(fileIds, plan, confirmationToken);
            onExecuted(mapExecutionResponse(response));
        }
        catch (err) {
            const e = err instanceof ApiError ? err : new ApiError({
                status: 0,
                errorCode: "network_error",
                message: "执行失败",
            });
            onError({ errorCode: e.errorCode, message: mapErrorCodeToMessage(e.errorCode, e.message) });
        }
    }, [onExecuted, onError]);
}
