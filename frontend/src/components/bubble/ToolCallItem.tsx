import { CaretDownOutlined } from "@ant-design/icons";
import { useState } from "react";

import type { ToolCallResult } from "../../domain/models";
import { SheetLinkChip } from "./SheetLinkChip";

type Props = {
  toolCall: ToolCallResult;
  defaultOpen?: boolean;
};

export function ToolCallItem({ toolCall, defaultOpen = false }: Props) {
  const [open, setOpen] = useState(defaultOpen);
  const status = toolCall.status ?? "running";
  const statusLabel = status === "ok" ? "成功" : status === "error" ? "失败" : "运行中";
  const chipName = toolCall.outputName ?? toolCall.outputId ?? null;

  return (
    <div
      className={`tool-call-item is-${status}`}
      data-testid={`tool-call-item-${toolCall.tool}`}
    >
      <button
        type="button"
        className="tool-call-header"
        onClick={() => setOpen((v) => !v)}
        data-testid={`tool-call-toggle-${toolCall.tool}`}
        aria-expanded={open}
      >
        <span className="tool-call-name">{toolCall.tool}</span>
        <span className="tool-call-status">{statusLabel}</span>
        <CaretDownOutlined rotate={open ? 180 : 0} className="tool-call-caret" />
      </button>
      {open && (
        <div className="tool-call-body" data-testid={`tool-call-body-${toolCall.tool}`}>
          {toolCall.summary && <div className="tool-call-summary">{toolCall.summary}</div>}
          {chipName && <SheetLinkChip outputName={chipName} />}
        </div>
      )}
    </div>
  );
}
