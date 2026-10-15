import { createContext, use, useCallback, useMemo, useState, type ReactNode } from "react";
import { useLocation } from "react-router";
import { useHistory } from "../api/history-api";
import type { LawAgentUIMessage } from "../types";
import { useChatSession, type ChatSession } from "../hooks/useChatSession";

type ChatSessionContextValue = {
  session: ChatSession;
  /** True on the new-chat screen, where the sources are still the user's to pick. */
  isNewChat: boolean;
  /** True while the thread the URL asks for is still being fetched. */
  isHydrating: boolean;
  hydrationError: unknown;
};

const ChatSessionContext = createContext<ChatSessionContextValue | null>(null);

export const useChatSessionContext = (): ChatSessionContextValue => {
  const value = use(ChatSessionContext);
  if (value === null) throw new Error("useChatSessionContext used outside ChatSessionProvider");
  return value;
};

type SessionMount = {
  /** Identity of the underlying chat state; changing it throws that state away. */
  key: string;
  /** The URL this mount is displayed at — null for the new-chat screen. */
  routeId: string | null;
  /** The thread the chat writes to; null until a new chat lazily creates one. */
  conversationId: string | null;
  initialMessages?: LawAgentUIMessage[];
};

let newChatCounter = 0;

// Never reuses a key, so two consecutive new chats cannot share a stale instance.
const newChatMount = (): SessionMount => ({
  key: `new-${++newChatCounter}`,
  routeId: null,
  conversationId: null,
});

const CHAT_PATH = /^\/chat\/(.+)$/;

const useRouteConversationId = (): string | null => {
  const { pathname } = useLocation();
  return CHAT_PATH.exec(pathname)?.[1] ?? null;
};

/*
 * The session lives above the router outlet on purpose. Sending the first message of a new
 * chat navigates to the thread it just created; were the session owned by the route, that
 * navigation would unmount the chat mid-stream and the answer would be lost to a `/history`
 * which, by design, stays empty until the turn completes.
 */
export const ChatSessionProvider = ({ children }: { children: ReactNode }) => {
  const routeConversationId = useRouteConversationId();
  const [mount, setMount] = useState<SessionMount>(newChatMount);

  const isAtRoute = mount.routeId === routeConversationId;
  /*
   * The URL points at the thread this session is already talking to — it is the new chat
   * whose id has just landed, so the router only has to be caught up with, not obeyed.
   */
  const isLiveThread = routeConversationId !== null && routeConversationId === mount.conversationId;
  const needsHistory = !isAtRoute && !isLiveThread && routeConversationId !== null;

  const history = useHistory(routeConversationId ?? "", { enabled: needsHistory });

  /*
   * The URL decides what is on screen and the mount follows it — adjusted during render
   * rather than in an effect, so a thread never paints on a route it does not belong to.
   */
  if (!isAtRoute) {
    if (isLiveThread) setMount({ ...mount, routeId: routeConversationId });
    else if (routeConversationId === null) setMount(newChatMount());
    else if (history.isSuccess) {
      setMount({
        key: routeConversationId,
        routeId: routeConversationId,
        conversationId: routeConversationId,
        initialMessages: history.data,
      });
    }
  }

  const handleConversationCreated = useCallback((id: string) => {
    // Only the id changes: holding on to the key keeps the chat that is mid-send alive.
    setMount((current) => ({ ...current, conversationId: id }));
  }, []);

  const session = useChatSession({
    sessionKey: mount.key,
    conversationId: mount.conversationId,
    initialMessages: mount.initialMessages,
    onConversationCreated: handleConversationCreated,
  });

  const value = useMemo<ChatSessionContextValue>(
    () => ({
      session,
      isNewChat: routeConversationId === null,
      isHydrating: needsHistory && history.isPending,
      hydrationError: needsHistory ? history.error : null,
    }),
    [session, routeConversationId, needsHistory, history.isPending, history.error],
  );

  return <ChatSessionContext value={value}>{children}</ChatSessionContext>;
};
