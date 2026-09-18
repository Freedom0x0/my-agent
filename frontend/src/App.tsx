import { useEffect, useState } from "react";
import {
  Prompts,
  Sender,
  Welcome,
  XProvider,
} from "@ant-design/x";
import {
  BarChartOutlined,
  ClearOutlined,
  FileSearchOutlined,
  MergeCellsOutlined,
  StopOutlined,
  VerticalLeftOutlined,
  VerticalRightOutlined,
} from "@ant-design/icons";

import { ChatList } from "./components/chat/ChatList";
import { ChatScroll } from "./components/chat/ChatScroll";
import { Previewer } from "./components/Previewer";
import { SessionSidebar } from "./components/SessionSidebar";
import { SenderPopover } from "./components/SenderPopover";
import { useAppStore, bootstrapApp } from "./hooks/useAppStore";

const theme = {
  token: {
    colorPrimary: "#2b4a8b",
    colorBgBase: "#fafaf9",
    colorBgContainer: "#ffffff",
    colorBgLayout: "#fafaf9",
    colorText: "#1f2328",
    colorTextSecondary: "#6b7280",
    colorBorder: "#e5e5e2",
    borderRadius: 8,
    fontFamily:
      '"Inter", "PingFang SC", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    fontSize: 14,
  },
  components: { Bubble: { borderRadius: 12 } },
};

const PROMPTS = [
  { key: "inspect", icon: <FileSearchOutlined />, label: "检查数据问题", description: "扫描空值、重复、类型异常" },
  { key: "normalize", icon: <ClearOutlined />, label: "统一格式并去重", description: "金额/日期字段统一，移除重复行" },
  { key: "aggregate", icon: <BarChartOutlined />, label: "按部门汇总", description: "按维度聚合，生成汇总表" },
  { key: "merge", icon: <MergeCellsOutlined />, label: "合并多个工作表", description: "跨 sheet 按公共字段对齐" },
];

export function App() {
  const status = useAppStore((s) => s.status);
  // Only the count — the list itself is owned by ChatList so streaming tokens
  // don't re-render the whole shell.
  const messageCount = useAppStore((s) => s.messages.length);
  const files = useAppStore((s) => s.files);
  const panel = useAppStore((s) => s.panel);
  const sendMessage = useAppStore((s) => s.sendMessage);
  const abortStream = useAppStore((s) => s.abortStream);
  const clearError = useAppStore((s) => s.clearError);
  const error = useAppStore((s) => s.error);
  const setPanelWidth = useAppStore((s) => s.setPanelWidth);
  const togglePanel = useAppStore((s) => s.togglePanel);

  const isProcessing = status === "processing";
  const hasFiles = files.length > 0;

  const [input, setInput] = useState("");

  useEffect(() => { void bootstrapApp(); }, []);

  const submit = (text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    if (isProcessing) {
      abortStream();
      return;
    }
    void sendMessage(trimmed);
    setInput("");
  };

  const handleCommand = (cmd: string) => {
    if (cmd === "/clear") {
      useAppStore.setState({ messages: [] });
      setInput("");
    } else if (cmd === "/new") {
      useAppStore.getState().createSession();
      setInput("");
    }
  };

  return (
    <XProvider theme={theme}>
      <div className="app-shell">
        <header className="app-header">
          <button
            type="button"
            className="header-collapse-btn"
            onClick={() => togglePanel("sider")}
            aria-label={panel.siderCollapsed ? "展开会话列表" : "收起会话列表"}
            data-testid="collapse-sider"
          >
            {panel.siderCollapsed ? <VerticalRightOutlined /> : <VerticalLeftOutlined />}
          </button>
          <div className="brand">
            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" style={{ flexShrink: 0 }}>
              <rect x="3" y="3" width="18" height="18" rx="4" fill="#2b4a8b" />
              <path d="M7 9h10M7 12h7M7 15h4" stroke="#fff" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
            <div className="brand-text">
              <h1 className="app-title">表析 Agent</h1>
              <span className="app-subtitle">AI 数据分析 · 表格处理 · 归因洞察</span>
            </div>
          </div>
          <button
            type="button"
            className="header-collapse-btn"
            onClick={() => togglePanel("preview")}
            aria-label={panel.previewCollapsed ? "展开预览面板" : "收起预览面板"}
            data-testid="collapse-preview"
          >
            {panel.previewCollapsed ? <VerticalLeftOutlined /> : <VerticalRightOutlined />}
          </button>
        </header>

        <main className="workspace">
          <aside
            className="workspace-sider"
            style={{ width: panel.siderWidth, display: panel.siderCollapsed ? "none" : undefined }}
          >
            <SessionSidebar />
          </aside>

          {!panel.siderCollapsed && (
            <div className="drag-handle" onMouseDown={(e) => {
              e.preventDefault();
              const sx = e.clientX, w0 = panel.siderWidth;
              const mv = (ev: MouseEvent) => setPanelWidth("sider", w0 + ev.clientX - sx);
              const up = () => { document.removeEventListener("mousemove", mv); document.removeEventListener("mouseup", up); };
              document.addEventListener("mousemove", mv); document.addEventListener("mouseup", up);
            }} />
          )}

          <section className="workspace-chat">
            {error && (
              <div className="chat-error" role="alert" onClick={clearError}>
                {error.message}
                <span className="chat-error-dismiss">×</span>
              </div>
            )}
            <ChatScroll testId="chat-history">
              {messageCount === 0 ? (
                <div className="chat-empty">
                  <Welcome icon={
                    <svg viewBox="0 0 64 64" width="64" height="64" fill="none">
                      <rect x="6" y="6" width="52" height="52" rx="12" fill="#2b4a8b" />
                      <g stroke="#fff" strokeWidth="2.6" strokeLinecap="round">
                        <path d="M16 22h32" /><path d="M16 32h22" /><path d="M16 42h14" />
                      </g>
                      <circle cx="50" cy="42" r="4" fill="#f3c969" />
                    </svg>
                  } title={hasFiles ? "想先做点什么？" : "欢迎使用"}
                  description={hasFiles ? "向 Agent 描述你的需求" : "上传 Excel 或 CSV 文件即可开始"}
                  variant="borderless" />
                  {hasFiles && <Prompts items={PROMPTS} onItemClick={(info) => { const p = PROMPTS.find((x) => x.key === info.data.key); if (p) { setInput(p.label); submit(p.label); } }} />}
                </div>
              ) : (
                <ChatList />
              )}
            </ChatScroll>
            <div className="chat-input-wrap">
              <SenderPopover
                value={input}
                onChange={setInput}
                files={files.map((f) => ({ id: f.id, name: f.name }))}
                onPickCommand={handleCommand}
              />
              <Sender
                value={input}
                onChange={setInput}
                onSubmit={(t) => submit(t)}
                placeholder={hasFiles ? "向 Agent 描述需求（@ 引用文件，/ 输入命令）" : "上传文件后可开始对话"}
                disabled={status === "uploading"}
                submitType="enter"
                autoSize={{ minRows: 2, maxRows: 6 }}
                data-testid="sender"
              />
              {isProcessing && (
                <button
                  type="button"
                  className="sender-stop-btn"
                  onClick={() => abortStream()}
                  data-testid="sender-stop-btn"
                  aria-label="停止生成"
                >
                  <StopOutlined /> 停止
                </button>
              )}
            </div>
          </section>

          {!panel.previewCollapsed && (
            <div className="drag-handle" onMouseDown={(e) => {
              e.preventDefault();
              const sx = e.clientX, w0 = panel.previewWidth;
              const mv = (ev: MouseEvent) => setPanelWidth("preview", w0 - (ev.clientX - sx));
              const up = () => { document.removeEventListener("mousemove", mv); document.removeEventListener("mouseup", up); };
              document.addEventListener("mousemove", mv); document.addEventListener("mouseup", up);
            }} />
          )}

          <aside
            className="workspace-preview"
            style={{ width: panel.previewWidth, display: panel.previewCollapsed ? "none" : undefined }}
          >
            <Previewer />
          </aside>
        </main>
      </div>
    </XProvider>
  );
}