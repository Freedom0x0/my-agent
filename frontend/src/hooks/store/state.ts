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
import type { ToolCallResult } from "../../domain/models";
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
  previewLoading: boolean;
  previewError: string | null;
  tabsBySession: Record<string, Tab[]>;
  activeTabBySession: Record<string, string>;
  streamingContent: string;
  streamingMessageId: string | null;
  streamController: AbortController | null;
  lastChatToolCalls: ToolCallResult[];
  lastChatSheets: string[];
  lastChatOutputId: string | null;
  error: UserFacingError | null;
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
  previewLoading: false,
  previewError: null,
  tabsBySession: {},
  activeTabBySession: {},
  streamingContent: "",
  streamingMessageId: null,
  streamController: null,
  lastChatToolCalls: [],
  lastChatSheets: [],
  lastChatOutputId: null,
  error: null,
};

export const SESSION_KEY = "tablex.current_session_id";
