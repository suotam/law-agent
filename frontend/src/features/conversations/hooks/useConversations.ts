import { useQuery } from "@tanstack/react-query";
import { listConversations } from "../api/conversations-api";

export const conversationQueryKeys = {
  all: ["conversations"] as const,
  detail: (id: string) => ["conversations", id] as const,
};

/** The API caps the list at 50 with no pagination; this mirrors that. */
export const CONVERSATION_LIST_CAP = 50;

export const useConversations = () =>
  useQuery({
    queryKey: conversationQueryKeys.all,
    queryFn: listConversations,
  });
