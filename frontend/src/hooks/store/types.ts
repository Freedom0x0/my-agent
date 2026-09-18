import type { PreviewTarget, Tab } from "../../domain/workflow";

// Re-export shared state types from state.ts so slice helpers can import
// everything from one place.
export type { WorkflowState, PanelState, ReactionValue } from "./state";
import type { ReactionValue } from "./state";

/** Which preview cache a tab refId belongs to. */
export type PreviewKind = "file" | "output";

export type Actions = {
  // Sidebar
  loadSessions: () => Promise<void>;
  selectSession: (id: string) => Promise<void>;
  createSession: () => string;
  removeSessionLocal: (id: string) => void;

  // Uploads
  uploadFile: (file: File) => Promise<void>;
  removeFile: (fileId: string) => void;
  /** Fetch + parse a tab's preview on demand; no-op when it's already cached. */
  ensurePreview: (
    kind: PreviewKind,
    refId: string,
    opts?: { force?: boolean; name?: string },
  ) => Promise<void>;

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

  // Streaming — all of these patch the tail message's `segments` in place
  appendTextDelta: (delta: string, opts?: { separate?: boolean }) => void;
  pushToolStart: (id: string, name: string) => void;
  resolveTool: (p: {
    id?: string;
    name: string;
    status: "ok" | "error";
    summary: string;
    outputId?: string | null;
    outputName?: string | null;
  }) => void;
  endStreamMessage: (meta?: {
    outputId?: string | null;
    outputName?: string | null;
    sheets?: string[];
  }) => void;
  abortStream: () => void;

  // Panels
  setPanelWidth: (side: "sider" | "preview", width: number) => void;
  togglePanel: (side: "sider" | "preview") => void;

  // Reactions (P)
  toggleReaction: (msgId: string, reaction: ReactionValue) => void;

  // Lazy load older (S)
  loadOlderMessages: () => Promise<void>;

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
