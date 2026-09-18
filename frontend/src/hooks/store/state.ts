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
};

export const SESSION_KEY = "tablex.current_session_id";
