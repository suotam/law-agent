import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { groupQueryKeys } from "./query-keys";

export const useAddGroupMember = (groupId: string) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (userId: string) =>
      apiClient.post(`/groups/${groupId}/members`, { user_id: userId }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: groupQueryKeys.members(groupId) });
    },
  });
};
