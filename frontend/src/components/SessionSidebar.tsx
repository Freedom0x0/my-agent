import { useEffect } from "react";
import { Conversations } from "@ant-design/x";
import type { ConversationItemType } from "@ant-design/x";
import type { MenuProps } from "antd";
import { PlusOutlined, SettingOutlined, UserOutlined } from "@ant-design/icons";

import { useAppStore } from "../hooks/useAppStore";

function relativeTime(iso: string): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const diff = Date.now() - t;
  const min = Math.floor(diff / 60_000);
  if (min < 1) return "刚刚";
  if (min < 60) return `${min} 分钟前`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} 小时前`;
  const day = Math.floor(hr / 24);
  if (day < 30) return `${day} 天前`;
  return new Date(iso).toLocaleDateString();
}

export function SessionSidebar() {
  const sessions = useAppStore((s) => s.sessions);
  const currentId = useAppStore((s) => s.currentSessionId);
  const selectSession = useAppStore((s) => s.selectSession);
  const createSession = useAppStore((s) => s.createSession);
  const loadSessions = useAppStore((s) => s.loadSessions);
  const removeSessionLocal = useAppStore((s) => s.removeSessionLocal);

  useEffect(() => {
    if (sessions.length === 0) loadSessions();
  }, [sessions.length, loadSessions]);

  const items = sessions.map((s) => ({
    key: s.sessionId,
    label: s.title || "新会话",
    timestamp: relativeTime(s.updatedAt),
    unread: s.messageCount,
  }));

  const buildMenu = (item: ConversationItemType): MenuProps => ({
    items: [
      { key: "rename", label: "重命名", disabled: true },
      { key: "delete", label: "删除", danger: true },
    ],
    onClick: ({ domEvent }) => {
      domEvent.stopPropagation();
      const key = String(item.key);
      if (confirm("删除该会话？")) removeSessionLocal(key);
    },
  });

  return (
    <div className="session-sidebar">
      <div className="session-sidebar-header">
        <button
          type="button"
          className="new-task-btn"
          onClick={() => createSession()}
          data-testid="new-task-btn"
        >
          <PlusOutlined /> 新工作任务
        </button>
      </div>

      <div className="session-group-title">历史任务</div>

      <Conversations
        className="session-list"
        items={items}
        activeKey={currentId ?? undefined}
        onActiveChange={(key) => selectSession(String(key))}
        menu={buildMenu}
      />

      <div className="user-footer">
        <span className="user-avatar"><UserOutlined /></span>
        <span className="user-name">gsr</span>
        <button type="button" className="user-settings" aria-label="设置">
          <SettingOutlined />
        </button>
      </div>
    </div>
  );
}