import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { LawAgentUIMessage } from "../types";

export const historyQueryKeys = {
  detail: (conversationId: string) => ["conversations", conversationId, "history"] as const,
};

/** The response is already the shape useChat hydrates from — no mapping needed. */
export const getHistory = async (conversationId: string): Promise<LawAgentUIMessage[]> => {
  const { data } = await apiClient.get<LawAgentUIMessage[]>(
    `/conversations/${conversationId}/history`,
  );
  return data;
};

type UseHistoryOptions = {
  /** Off for a thread already held live in memory, whose archive is still incomplete. */
  enabled?: boolean;
};

export const useHistory = (conversationId: string, { enabled = true }: UseHistoryOptions = {}) =>
  useQuery({
    queryKey: historyQueryKeys.detail(conversationId),
    queryFn: () => getHistory(conversationId),
    enabled,
    staleTime: Infinity,
  });
