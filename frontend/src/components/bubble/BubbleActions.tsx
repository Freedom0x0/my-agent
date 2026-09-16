import { CheckOutlined, CopyOutlined, DislikeOutlined, LikeOutlined } from "@ant-design/icons";
import { useState } from "react";

import { useAppStore } from "../../hooks/useAppStore";
import type { ChatMessage } from "../../domain/models";

type Props = {
  message: ChatMessage;
};

export function BubbleActions({ message }: Props) {
  const reaction = useAppStore((s) => s.messageReactions[message.id] ?? null);
  const toggleReaction = useAppStore((s) => s.toggleReaction);
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(message.content);
      }
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    }
  };

  return (
    <div className="bubble-actions" data-testid={`bubble-actions-${message.id}`}>
      <button
        type="button"
        className={`bubble-action-btn ${copied ? "is-active" : ""}`}
        onClick={handleCopy}
        data-testid={`copy-btn-${message.id}`}
        aria-label={copied ? "已复制" : "复制"}
        title={copied ? "已复制" : "复制"}
      >
        {copied ? <CheckOutlined /> : <CopyOutlined />}
        <span>{copied ? "已复制" : "复制"}</span>
      </button>
      <button
        type="button"
        className={`bubble-action-btn ${reaction === "up" ? "is-active" : ""}`}
        onClick={() => toggleReaction(message.id, "up")}
        data-testid={`thumb-up-${message.id}`}
        aria-label="点赞"
        title="点赞"
      >
        <LikeOutlined />
      </button>
      <button
        type="button"
        className={`bubble-action-btn ${reaction === "down" ? "is-active" : ""}`}
        onClick={() => toggleReaction(message.id, "down")}
        data-testid={`thumb-down-${message.id}`}
        aria-label="点踩"
        title="点踩"
      >
        <DislikeOutlined />
      </button>
    </div>
  );
}