import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { RoleCapability } from "@/features/auth";
import type { RoleResponse } from "../types";
import { roleQueryKeys } from "./query-keys";

type UpdateRoleCapabilitiesRequest = {
  id: string;
  capabilities: RoleCapability[];
};

export const updateRoleCapabilities = async ({
  id,
  capabilities,
}: UpdateRoleCapabilitiesRequest): Promise<RoleResponse> => {
  const { data } = await apiClient.put<RoleResponse>(`/roles/${id}/capabilities`, { capabilities });
  return data;
};

export const useUpdateRoleCapabilities = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: updateRoleCapabilities,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: roleQueryKeys.list });
    },
  });
};
