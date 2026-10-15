import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { RoleResponse } from "../types";
import { roleQueryKeys } from "./query-keys";

type RenameRoleRequest = {
  id: string;
  name: string;
};

export const renameRole = async ({ id, name }: RenameRoleRequest): Promise<RoleResponse> => {
  const { data } = await apiClient.patch<RoleResponse>(`/roles/${id}`, { name });
  return data;
};

export const useRenameRole = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: renameRole,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: roleQueryKeys.list });
    },
  });
};
