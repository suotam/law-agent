import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { userQueryKeys } from "./query-keys";

/** Soft delete: the row stays, only `is_active` flips -- reactivating is undo. */
export const useDeactivateUser = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (id: string) => {
      await apiClient.delete(`/users/${id}`);
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: userQueryKeys.list });
    },
  });
};
