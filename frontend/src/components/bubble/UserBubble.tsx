import { CheckOutlined, CloseOutlined, EditOutlined } from "@ant-design/icons";
import { useState } from "react";

import { useAppStore } from "../../hooks/useAppStore";
import type { ChatMessage } from "../../domain/models";

type Props = {
  id: string;
};

export function UserBubble({ id }: Props) {
  const message = useAppStore((s) => s.messages.find((m) => m.id === id));
  const sendMessage = useAppStore((s) => s.sendMessage);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(message?.content ?? "");

  if (!message) return null;

  const startEdit = () => {
    setDraft(message.content);
    setEditing(true);
  };

  const cancelEdit = () => {
    setEditing(false);
    setDraft(message.content);
  };

  const saveEdit = async () => {
    const next = draft.trim();
    if (!next || next === message.content) {
      cancelEdit();
      return;
    }
    // Read the live list off the store rather than subscribing to it — this bubble
    // would otherwise re-render on every streamed token.
    const messages = useAppStore.getState().messages;
    const idx = messages.findIndex((m) => m.id === message.id);
    if (idx < 0) {
      setEditing(false);
      return;
    }
    const following = messages.length - idx - 1;
    if (following > 0) {
      const ok = window.confirm(`将丢失 ${following} 条后续消息，确认？`);
      if (!ok) return;
    }
    const truncated = messages.slice(0, idx);
    const replaced: ChatMessage = { ...message, content: next };
    useAppStore.setState({
      messages: [...truncated, replaced],
      streamingMessageId: null,
    });
    setEditing(false);
    await sendMessage(next);
  };

  if (editing) {
    return (
      <div className="user-bubble is-editing" data-testid={`user-bubble-${message.id}`}>
        <textarea
          className="user-bubble-textarea"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          data-testid={`user-bubble-textarea-${message.id}`}
          rows={3}
        />
        <div className="user-bubble-edit-actions">
          <button
            type="button"
            className="bubble-action-btn is-primary"
            onClick={saveEdit}
            data-testid={`user-bubble-save-${message.id}`}
          >
            <CheckOutlined />
            <span>保存</span>
          </button>
          <button
            type="button"
            className="bubble-action-btn"
            onClick={cancelEdit}
            data-testid={`user-bubble-cancel-${message.id}`}
          >
            <CloseOutlined />
            <span>取消</span>
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="user-bubble" data-testid={`user-bubble-${message.id}`}>
      <div className="user-bubble-content">{message.content}</div>
      <div className="bubble-actions">
        <button
          type="button"
          className="bubble-action-btn"
          onClick={startEdit}
          data-testid={`user-bubble-edit-${message.id}`}
          aria-label="编辑"
          title="编辑"
        >
          <EditOutlined />
          <span>编辑</span>
        </button>
      </div>
    </div>
  );
}