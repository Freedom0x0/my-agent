import { chat, chatStream } from "./chat";
import { download, downloadUploadedFile, downloadUrl, uploadFile } from "./files";
import {
  executeWorkflow,
  getSession,
  getWorkflow,
  listSessions,
  pauseWorkflow,
} from "./sessions";

export type { StreamEvent, StreamToolCall } from "./chat";
export type { ExecuteEvent } from "./sessions";
export { chatStream, readSseStream } from "./chat";

export const api = {
  uploadFile,
  chat,
  chatStream,
  listSessions,
  getSession,
  getWorkflow,
  executeWorkflow,
  pauseWorkflow,
  downloadUrl,
  download,
  downloadUploadedFile,
};
