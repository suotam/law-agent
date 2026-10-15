import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { roleQueryKeys } from "./query-keys";

export const deleteRole = async (id: string): Promise<void> => {
  await apiClient.delete(`/roles/${id}`);
};

export const useDeleteRole = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: deleteRole,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: roleQueryKeys.list });
    },
  });
};
