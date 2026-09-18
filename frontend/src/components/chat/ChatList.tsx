import { useMemo } from "react";
import { Bubble } from "@ant-design/x";
import type { BubbleItemType } from "@ant-design/x/es/bubble";
import { RobotOutlined, UserOutlined } from "@ant-design/icons";

import { useAppStore } from "../../hooks/useAppStore";
import { AssistantBubble } from "../bubble/AssistantBubble";
import { UserBubble } from "../bubble/UserBubble";

const userAvatar = <UserOutlined />;
const agentAvatar = <RobotOutlined />;

const BUBBLE_ROLE = {
  user: { placement: "end" as const, variant: "filled" as const, shape: "round" as const, avatar: userAvatar },
  assistant: { placement: "start" as const, variant: "outlined" as const, shape: "round" as const, avatar: agentAvatar },
};

/**
 * Owns the message list so a streamed token doesn't re-render the whole app.
 *
 * Subscribing to a joined id string keeps this component still during a turn —
 * the id list only changes when a message is added or removed, while the
 * per-token churn is handled by each bubble's own selector.
 */
export function ChatList() {
  const signature = useAppStore((s) =>
    s.messages.map((m) => `${m.role}:${m.id}`).join("|"),
  );

  const items = useMemo<BubbleItemType[]>(
    () =>
      signature
        ? signature.split("|").map((entry) => {
            const sep = entry.indexOf(":");
            const role = entry.slice(0, sep);
            const id = entry.slice(sep + 1);
            return {
              key: id,
              role: role === "user" ? ("user" as const) : ("assistant" as const),
              content: role === "user" ? <UserBubble id={id} /> : <AssistantBubble id={id} />,
            };
          })
        : [],
    [signature],
  );

  return <Bubble.List role={BUBBLE_ROLE} items={items} autoScroll />;
}