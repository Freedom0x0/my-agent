import { useCallback } from "react";

import { api, ApiError } from "../api/httpClient";
import { mapErrorCodeToMessage, mapUploadResponse } from "../api/mappers";
import type { FileItem } from "../domain/models";

export function useUpload(
  onUploaded: (file: FileItem) => void,
  onError: (error: { errorCode: string; message: string }) => void,
) {
  return useCallback(
    async (file: File) => {
      try {
        const response = await api.uploadFile(file);
        const mapped = mapUploadResponse(response);
        onUploaded({
          id: mapped.id,
          name: mapped.name,
          sizeBytes: mapped.sizeBytes,
          sheets: mapped.sheets,
        });
      } catch (err) {
        const e = err instanceof ApiError ? err : new ApiError({
          status: 0,
          errorCode: "network_error",
          message: "上传失败",
        });
        onError({ errorCode: e.errorCode, message: mapErrorCodeToMessage(e.errorCode, e.message) });
      }
    },
    [onUploaded, onError],
  );
}