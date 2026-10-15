import { useCallback, useEffect, useRef } from "react";

/** Within this distance of the bottom the user still counts as following the answer. */
const FOLLOW_THRESHOLD_PX = 80;

/*
 * A streaming answer grows the content, not the scroll container, so nothing in React tells us
 * when to scroll — the growth itself is the signal. Scrolling away from the bottom is read as a
 * decision to stay put (the user is re-reading something), and returning there resumes the
 * following, which is why the intent lives in a ref and never triggers a render.
 */
export const useStickToBottom = (sessionKey: string) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const isFollowingRef = useRef(true);

  /*
   * Sending overrides a scroll-up: the user asked for the new turn, so they mean to watch it.
   * The container may not exist yet — the first message of a new chat creates it — so this
   * restores the intent and leaves the scrolling to the observer that sees the bubble appear.
   */
  const scrollToBottom = useCallback(() => {
    isFollowingRef.current = true;

    const container = containerRef.current;
    if (container) container.scrollTop = container.scrollHeight;
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    const content = container?.firstElementChild;
    if (!container || !content) return;

    const handleScroll = () => {
      const distance = container.scrollHeight - container.scrollTop - container.clientHeight;
      isFollowingRef.current = distance <= FOLLOW_THRESHOLD_PX;
    };

    const observer = new ResizeObserver(() => {
      if (isFollowingRef.current) container.scrollTop = container.scrollHeight;
    });

    observer.observe(content);
    container.addEventListener("scroll", handleScroll, { passive: true });
    // A thread always opens at its newest message, however the previous one was left.
    isFollowingRef.current = true;
    container.scrollTop = container.scrollHeight;

    return () => {
      observer.disconnect();
      container.removeEventListener("scroll", handleScroll);
    };
    // Re-armed per thread: switching threads must not inherit the last one's scroll intent.
  }, [sessionKey]);

  return { containerRef, scrollToBottom };
};
