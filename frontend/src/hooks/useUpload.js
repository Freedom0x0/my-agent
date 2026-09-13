import { useCallback } from "react";
import { api, ApiError } from "../api/httpClient";
import { mapErrorCodeToMessage, mapUploadResponse } from "../api/mappers";
export function useUpload(onUploaded, onError) {
    return useCallback(async (file) => {
        try {
            const response = await api.uploadFile(file);
            const mapped = mapUploadResponse(response);
            onUploaded({
                id: mapped.id,
                name: mapped.name,
                sizeBytes: mapped.sizeBytes,
                sheets: mapped.sheets,
            });
        }
        catch (err) {
            const e = err instanceof ApiError ? err : new ApiError({
                status: 0,
                errorCode: "network_error",
                message: "上传失败",
            });
            onError({ errorCode: e.errorCode, message: mapErrorCodeToMessage(e.errorCode, e.message) });
        }
    }, [onUploaded, onError]);
}
