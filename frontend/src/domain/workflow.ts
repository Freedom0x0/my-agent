import type {
  AppStatus,
  ChatMessage,
  FileItem,
  UserFacingError,
  WorkbookPreview,
} from "./models";

// Re-export types so consumers can import everything from one place.
export type { AppStatus, ChatMessage, FileItem, UserFacingError, WorkbookPreview };

export type SessionSummary = {
  sessionId: string;
  title: string;
  updatedAt: string;
  messageCount: number;
  lastUserMsg: string;
};

export type PreviewTarget =
  | { kind: "file"; fileId: string }
  | { kind: "output"; outputId: string };

export type PanelState = {
  siderWidth: number;
  previewWidth: number;
  siderCollapsed: boolean;
  previewCollapsed: boolean;
};

export type TabKind = "file" | "output";

export type Tab = {
  id: string;
  kind: TabKind;
  refId: string;
  fileName: string;
  openedAt: number;
};

export type WorkflowState = {
  // Sidebar
  sessions: SessionSummary[];
  sessionsLoading: boolean;

  // Current session
  currentSessionId: string | null;
  status: AppStatus;
  files: FileItem[];
  messages: ChatMessage[];
  outputIds: string[];

  // Panels
  panel: PanelState;

  // Previewer
  activePreview: PreviewTarget | null;
  filePreviews: Record<string, WorkbookPreview>;
  outputPreviews: Record<string, WorkbookPreview>;
  previewLoading: boolean;
  previewError: string | null;

  // Per-session tab isolation (persisted)
  tabsBySession: Record<string, Tab[]>;
  activeTabBySession: Record<string, string>;

  // Streaming
  streamingContent: string;

  // Output of the last chat (for chat-bubble chip linking)
  lastChatSheets: string[];
  lastChatOutputId: string | null;

  error: UserFacingError | null;
};

export const DEFAULT_SIDER_WIDTH = 280;
export const DEFAULT_PREVIEW_WIDTH = 380;
export const SIDER_MIN = 240;
export const SIDER_MAX = 480;
export const PREVIEW_MIN = 280;
export const PREVIEW_MAX = 720;

export function newSessionId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return Math.random().toString(36).slice(2);
}

export function newTabId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `tab-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}