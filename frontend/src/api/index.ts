import { chat } from "./chat";
import { download, downloadUrl, uploadFile } from "./files";
import { getSession, listSessions } from "./sessions";

export const api = {
  uploadFile,
  chat,
  listSessions,
  getSession,
  downloadUrl,
  download,
};
