import { DefaultChatTransport } from "ai";
import { clearSession, getToken } from "@/features/auth";
import { ChatHttpError } from "@/lib/errors";
import type { LawAgentUIMessage, SendMessageRequest } from "../types";

/*
 * Getters rather than refs: both values are decided moments before a request goes out,
 * so they have to be read at request time — but the transport itself has no business
 * knowing they happen to live in React refs.
 */
export type ChatRequestContext = {
  getConversationId: () => string | null;
  getAttachmentIds: () => string[];
};

const API_URL: string = import.meta.env.VITE_BACKEND_API_URL;

/*
 * Streaming goes over fetch, not axios, so the axios interceptor covers neither the
 * auth header nor the 401 handling here. This wrapper is the transport's equivalent.
 */
const fetchWithAuth: typeof fetch = async (input, init) => {
  const response = await fetch(input, init);

  if (response.ok) return response;

  if (response.status === 401) clearSession();

  throw new ChatHttpError(response.status);
};

export const createChatTransport = (context: ChatRequestContext) =>
  new DefaultChatTransport<LawAgentUIMessage>({
    api: `${API_URL}/conversations`,
    fetch: fetchWithAuth,
    // useChat posts an array of messages to a fixed URL; the API wants a per-thread
    // URL and a single question, so the two are mapped here.
    prepareSendMessagesRequest: ({ messages }) => {
      const conversationId = context.getConversationId();
      if (conversationId === null) {
        // ensureConversation() is always awaited before sendMessage; reaching here is a bug.
        throw new Error("chat transport ran before a conversation existed");
      }

      const lastMessage = messages.at(-1);
      const question = (lastMessage?.parts ?? [])
        .filter((part) => part.type === "text")
        .map((part) => part.text)
        .join("");

      const body: SendMessageRequest = {
        question,
        attachment_ids: context.getAttachmentIds(),
      };

      return {
        api: `${API_URL}/conversations/${conversationId}/messages`,
        headers: { Authorization: `Bearer ${getToken() ?? ""}` },
        body,
      };
    },
  });
