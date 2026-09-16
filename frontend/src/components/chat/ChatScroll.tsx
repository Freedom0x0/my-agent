import { LoadingOutlined } from "@ant-design/icons";
import { useCallback, useEffect, useRef } from "react";

import { useAppStore } from "../../hooks/useAppStore";

type Props = {
  children: React.ReactNode;
  testId?: string;
};

const TOP_THRESHOLD = 80;

export function ChatScroll({ children, testId }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const sid = useAppStore((s) => s.currentSessionId);
  const hasMore = useAppStore((s) => (sid ? s.sessionHasMore[sid] ?? false : false));
  const loadingOlder = useAppStore((s) => s.sessionLoadingOlder);
  const loadOlderMessages = useAppStore((s) => s.loadOlderMessages);
  const loadGuard = useRef(false);

  const handleScroll = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    if (loadGuard.current) return;
    if (el.scrollTop > TOP_THRESHOLD) return;
    if (!hasMore || loadingOlder) return;
    const prevHeight = el.scrollHeight;
    const prevTop = el.scrollTop;
    loadGuard.current = true;
    void loadOlderMessages().then(() => {
      requestAnimationFrame(() => {
        if (!ref.current) return;
        const delta = ref.current.scrollHeight - prevHeight;
        ref.current.scrollTop = Math.max(0, prevTop + delta);
        loadGuard.current = false;
      });
    });
  }, [hasMore, loadingOlder, loadOlderMessages]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.addEventListener("scroll", handleScroll, { passive: true });
    return () => el.removeEventListener("scroll", handleScroll);
  }, [handleScroll]);

  return (
    <div
      ref={ref}
      className="chat-scroll"
      data-testid={testId ?? "chat-scroll"}
    >
      {loadingOlder && (
        <div className="chat-load-older" data-testid="chat-load-older">
          <LoadingOutlined /> 加载更早的消息…
        </div>
      )}
      {children}
    </div>
  );
}