import type { ToolCallResult } from "../../domain/models";
import { SheetLinkChip } from "./SheetLinkChip";

type Props = {
  toolCall: ToolCallResult;
  outputName?: string | null;
};

export function ToolInline({ toolCall, outputName }: Props) {
  const chipName = outputName ?? toolCall.outputName ?? null;
  return (
    <span
      className="tool-inline"
      data-testid={`tool-inline-${toolCall.tool}`}
    >
      <span className="tool-inline-name">{toolCall.tool}</span>
      {chipName && <SheetLinkChip outputName={chipName} />}
    </span>
  );
}