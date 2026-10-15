import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { groupQueryKeys } from "./query-keys";

export const useRemoveGroupMember = (groupId: string) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (userId: string) => apiClient.delete(`/groups/${groupId}/members/${userId}`),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: groupQueryKeys.members(groupId) });
    },
  });
};
