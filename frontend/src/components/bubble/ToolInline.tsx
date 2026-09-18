import { CheckCircleOutlined, CloseCircleOutlined, LoadingOutlined } from "@ant-design/icons";

import type { ToolCallResult } from "../../domain/models";
import { SheetLinkChip } from "./SheetLinkChip";

type Props = {
  toolCall: ToolCallResult;
  outputName?: string | null;
};

export function ToolInline({ toolCall, outputName }: Props) {
  const chipName = outputName ?? toolCall.outputName ?? null;
  const { status, summary } = toolCall;
  return (
    <span
      className={`tool-inline is-${status}`}
      data-testid={`tool-inline-${toolCall.tool}`}
    >
      <span className="tool-inline-icon" aria-hidden>
        {status === "running" ? (
          <LoadingOutlined spin />
        ) : status === "error" ? (
          <CloseCircleOutlined />
        ) : (
          <CheckCircleOutlined />
        )}
      </span>
      <span className="tool-inline-name">{toolCall.tool}</span>
      {summary ? (
        <span className="tool-inline-summary" title={summary}>
          {summary}
        </span>
      ) : null}
      <span className="sr-only">{statusText(status)}</span>
      {chipName && <SheetLinkChip outputName={chipName} />}
    </span>
  );
}

function statusText(status: ToolCallResult["status"]): string {
  if (status === "running") return "执行中";
  return status === "error" ? "失败" : "成功";
}