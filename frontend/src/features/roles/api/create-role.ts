import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { RoleResponse } from "../types";
import { roleQueryKeys } from "./query-keys";

type CreateRoleRequest = {
  name: string;
};

export const createRole = async (payload: CreateRoleRequest): Promise<RoleResponse> => {
  const { data } = await apiClient.post<RoleResponse>("/roles", payload);
  return data;
};

export const useCreateRole = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: createRole,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: roleQueryKeys.list });
    },
  });
};
