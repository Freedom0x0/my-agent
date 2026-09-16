import type { PreviewTarget, Tab } from "../../domain/workflow";

// Re-export shared state types from state.ts so slice helpers can import
// everything from one place.
export type { WorkflowState, PanelState } from "./state";

export type Actions = {
  // Sidebar
  loadSessions: () => Promise<void>;
  selectSession: (id: string) => Promise<void>;
  createSession: () => string;
  removeSessionLocal: (id: string) => void;

  // Uploads
  uploadFile: (file: File) => Promise<void>;
  removeFile: (fileId: string) => void;

  // Chat
  sendMessage: (text: string) => Promise<void>;

  // Previewer / Tabs
  setActivePreview: (target: PreviewTarget | null) => void;
  showOutput: (outputId: string) => void;
  showFile: (fileId: string) => void;
  addTab: (sessionId: string, tab: Omit<Tab, "id" | "openedAt">) => string;
  addEmptyTab: (sessionId: string) => string;
  removeTab: (sessionId: string, tabId: string) => void;
  setActiveTab: (sessionId: string, tabId: string) => void;

  // Streaming
  appendStream: (token: string) => void;
  finishStream: () => void;
  abortStream: () => void;

  // Panels
  setPanelWidth: (side: "sider" | "preview", width: number) => void;
  togglePanel: (side: "sider" | "preview") => void;

  // Error
  clearError: () => void;
};

export function newMessageId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `m-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function tabToPreview(t: Tab): PreviewTarget {
  return t.kind === "file" ? { kind: "file", fileId: t.refId } : { kind: "output", outputId: t.refId };
}
