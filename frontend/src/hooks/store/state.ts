import type {
  ChatMessage,
  FileItem,
  PreviewTarget,
  SessionSummary,
  Tab,
  UserFacingError,
  WorkbookPreview,
  AppStatus,
} from "../../domain/workflow";
import type { Graph, Stage } from "../../domain/graph";
import {
  DEFAULT_SIDER_WIDTH,
  DEFAULT_PREVIEW_WIDTH,
} from "../../domain/workflow";

export type PanelState = {
  siderWidth: number;
  previewWidth: number;
  siderCollapsed: boolean;
  previewCollapsed: boolean;
};

export type ReactionValue = "up" | "down" | null;

/** Workspace view tab — chat transcript or workflow canvas. Bottom action bar and
 *  input are shared by both, so the user can talk about the graph without leaving it. */
export type WorkspaceView = "chat" | "canvas";

/** Right-pane tab — node detail (canvas) or the existing file/output previewer. */
export type RightPanelTab = "node" | "file";

export type WorkflowState = {
  sessions: SessionSummary[];
  sessionsLoading: boolean;
  currentSessionId: string | null;
  status: AppStatus;
  files: FileItem[];
  messages: ChatMessage[];
  outputIds: string[];
  panel: PanelState;
  activePreview: PreviewTarget | null;
  filePreviews: Record<string, WorkbookPreview>;
  outputPreviews: Record<string, WorkbookPreview>;
  previewErrors: Record<string, string>;
  tabsBySession: Record<string, Tab[]>;
  activeTabBySession: Record<string, string>;
  streamingMessageId: string | null;
  streamController: AbortController | null;
  lastChatSheets: string[];
  lastChatOutputId: string | null;
  lastChatOutputName: string | null;
  error: UserFacingError | null;
  messageReactions: Record<string, ReactionValue>;
  sessionHasMore: Record<string, boolean>;
  sessionLoadingOlder: boolean;
  oldestLoadedIndexBySession: Record<string, number>;

  // Workflow graph (transient — refetched per session, never persisted)
  graph: Graph | null;
  graphStage: Stage | null;
  selectedNodeId: string | null;
  workspaceView: WorkspaceView;
  rightPanel: RightPanelTab;
  chatUnread: boolean;
  /** Live SSE reader for a running graph — aborted on session switch / unmount. */
  executeController: AbortController | null;
  /** User asked to pause; the run keeps going until the current node finishes. */
  pauseRequested: boolean;
};

export const initial: WorkflowState = {
  sessions: [],
  sessionsLoading: false,
  currentSessionId: null,
  status: "idle",
  files: [],
  messages: [],
  outputIds: [],
  panel: {
    siderWidth: DEFAULT_SIDER_WIDTH,
    previewWidth: DEFAULT_PREVIEW_WIDTH,
    siderCollapsed: false,
    previewCollapsed: false,
  },
  activePreview: null,
  filePreviews: {},
  outputPreviews: {},
  previewErrors: {},
  tabsBySession: {},
  activeTabBySession: {},
  streamingMessageId: null,
  streamController: null,
  lastChatSheets: [],
  lastChatOutputId: null,
  lastChatOutputName: null,
  error: null,
  messageReactions: {},
  sessionHasMore: {},
  sessionLoadingOlder: false,
  oldestLoadedIndexBySession: {},
  graph: null,
  graphStage: null,
  selectedNodeId: null,
  workspaceView: "chat",
  rightPanel: "file",
  chatUnread: false,
  executeController: null,
  pauseRequested: false,
};

export const SESSION_KEY = "tablex.current_session_id";
