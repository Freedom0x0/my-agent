import { chat, chatStream } from "./chat";
import { download, downloadUrl, uploadFile } from "./files";
import { getSession, listSessions } from "./sessions";

export type { StreamEvent, StreamToolCall } from "./chat";
export { chatStream, readSseStream } from "./chat";

export const api = {
  uploadFile,
  chat,
  chatStream,
  listSessions,
  getSession,
  downloadUrl,
  download,
};
