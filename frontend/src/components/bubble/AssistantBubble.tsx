import { useAppStore } from "../../hooks/useAppStore";
import type { ChatMessage } from "../../domain/models";
import { BubbleActions } from "./BubbleActions";
import { MarkdownContent } from "./MarkdownContent";
import { ToolProgressBar } from "./ToolProgressBar";

type Props = {
  message: ChatMessage;
  isStreaming?: boolean;
};

export function AssistantBubble({ message, isStreaming = false }: Props) {
  const streamingId = useAppStore((s) => s.streamingMessageId);
  const liveToolCalls = useAppStore((s) => s.lastChatToolCalls);
  const isLive = isStreaming || streamingId === message.id;
  const toolCalls = isLive ? liveToolCalls : message.toolCalls ?? [];
  const knownFileIds = useAppStore((s) => s.files).map((f) => f.id);

  return (
    <div className="assistant-bubble" data-testid={`assistant-bubble-${message.id}`}>
      {toolCalls.length > 0 && (
        <ToolProgressBar messageId={message.id} toolCalls={toolCalls} isStreaming={isLive} />
      )}
      <div className="assistant-bubble-content">
        <MarkdownContent
          content={message.content}
          sheets={message.sheets ?? []}
          outputId={message.outputId ?? null}
          outputName={message.outputName ?? null}
          knownFileIds={knownFileIds}
        />
      </div>
      <BubbleActions message={message} />
    </div>
  );
}