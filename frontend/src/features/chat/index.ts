export { createChatTransport, type ChatRequestContext } from "./api/chat-transport";
export { getHistory, historyQueryKeys, useHistory } from "./api/history-api";
export { AssistantMessage } from "./components/AssistantMessage";
export { ChatScreen } from "./components/ChatScreen";
export { ChatSessionProvider, useChatSessionContext } from "./components/ChatSessionProvider";
export { MessageList } from "./components/MessageList";
export { useChatSession, type ChatSession } from "./hooks/useChatSession";
export { useEnsureConversation, type EnsureConversation } from "./hooks/useEnsureConversation";
export { useStickToBottom } from "./hooks/useStickToBottom";
export { useThreadSources } from "./hooks/useThreadSources";
export {
  buildThreadSources,
  collectCitedRefs,
  collectSourceItems,
  MARKER_PATTERN,
  threadSourcesSignature,
  type ThreadSources,
} from "./utils/citations";
export type {
  LawAgentDataParts,
  LawAgentUIMessage,
  SendMessageRequest,
  SourceItem,
  SourceKind,
} from "./types";
