import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { GroupResponse } from "../types";
import { groupQueryKeys } from "./query-keys";

type RenameGroupRequest = {
  id: string;
  name: string;
};

export const renameGroup = async ({ id, name }: RenameGroupRequest): Promise<GroupResponse> => {
  const { data } = await apiClient.patch<GroupResponse>(`/groups/${id}`, { name });
  return data;
};

export const useRenameGroup = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: renameGroup,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: groupQueryKeys.list });
    },
  });
};
