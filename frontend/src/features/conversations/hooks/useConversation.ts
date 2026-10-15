import { useQuery } from "@tanstack/react-query";
import { getConversation } from "../api/conversations-api";
import { conversationQueryKeys } from "./useConversations";

export const useConversation = (id: string) =>
  useQuery({
    queryKey: conversationQueryKeys.detail(id),
    queryFn: () => getConversation(id),
    // The scope is frozen at creation, so the detail never changes for a given id.
    staleTime: Infinity,
  });
