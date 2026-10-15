import { useMutation, useQueryClient } from "@tanstack/react-query";
import { deleteConversation } from "../api/conversations-api";
import { conversationQueryKeys } from "./useConversations";

export const useDeleteConversation = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: deleteConversation,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: conversationQueryKeys.all });
    },
  });
};
