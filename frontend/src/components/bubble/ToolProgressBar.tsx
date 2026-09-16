import { CaretDownOutlined, CaretRightOutlined } from "@ant-design/icons";
import { useState } from "react";

import { useAppStore } from "../../hooks/useAppStore";
import type { ToolCallResult } from "../../domain/models";

type Props = {
  messageId: string;
  toolCalls: ToolCallResult[];
  isStreaming?: boolean;
};

export function ToolProgressBar({ messageId, toolCalls, isStreaming = false }: Props) {
  const [expanded, setExpanded] = useState(false);
  const status = useAppStore((s) => s.status);
  const streamingId = useAppStore((s) => s.streamingMessageId);
  const isLive = isStreaming || (streamingId === messageId);

  if (!toolCalls.length) return null;

  const latest = toolCalls[toolCalls.length - 1];
  const inFlight = isLive && status === "processing";
  const summary = inFlight
    ? `正在调用 ${latest.tool}…`
    : `已完成 ${toolCalls.length} 个工具调用`;
  const okCount = toolCalls.filter((t) => t.status === "ok").length;
  const errCount = toolCalls.length - okCount;

  return (
    <div className="tool-progress" data-testid={`tool-progress-${messageId}`}>
      <button
        type="button"
        className="tool-progress-bar"
        onClick={() => setExpanded((v) => !v)}
        data-testid={`tool-progress-toggle-${messageId}`}
        aria-expanded={expanded}
      >
        <span className="tool-progress-icon">{expanded ? <CaretDownOutlined /> : <CaretRightOutlined />}</span>
        <span className="tool-progress-summary">{summary}</span>
        {okCount > 0 && <span className="tool-progress-pill is-ok">{okCount} ok</span>}
        {errCount > 0 && <span className="tool-progress-pill is-err">{errCount} err</span>}
      </button>
      {expanded && (
        <ul className="tool-timeline" data-testid={`tool-timeline-${messageId}`}>
          {toolCalls.map((tc, i) => (
            <li
              key={i}
              className={`tool-timeline-item ${tc.status === "ok" ? "is-ok" : "is-err"}`}
            >
              <span className="tool-timeline-dot" />
              <span className="tool-timeline-tool">{tc.tool}</span>
              <span className="tool-timeline-summary">{tc.summary}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}