import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { groupQueryKeys } from "./query-keys";

export const deleteGroup = async (id: string): Promise<void> => {
  await apiClient.delete(`/groups/${id}`);
};

export const useDeleteGroup = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: deleteGroup,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: groupQueryKeys.list });
    },
  });
};
