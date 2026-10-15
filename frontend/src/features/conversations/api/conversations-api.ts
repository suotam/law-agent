import { apiClient } from "@/lib/api-client";
import type { ConversationDetail, ConversationResponse, CreateConversationRequest } from "../types";

export const listConversations = async (): Promise<ConversationResponse[]> => {
  const { data } = await apiClient.get<ConversationResponse[]>("/conversations");
  return data;
};

export const getConversation = async (id: string): Promise<ConversationDetail> => {
  const { data } = await apiClient.get<ConversationDetail>(`/conversations/${id}`);
  return data;
};

export const createConversation = async (
  payload: CreateConversationRequest,
): Promise<ConversationResponse> => {
  // scope is always sent, including as []: an absent scope means *both* corpora server-side.
  const { data } = await apiClient.post<ConversationResponse>("/conversations", payload);
  return data;
};

export const deleteConversation = async (id: string): Promise<void> => {
  await apiClient.delete(`/conversations/${id}`);
};
