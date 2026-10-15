import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { GroupResponse } from "../types";
import { groupQueryKeys } from "./query-keys";

type CreateGroupRequest = {
  name: string;
};

export const createGroup = async (payload: CreateGroupRequest): Promise<GroupResponse> => {
  const { data } = await apiClient.post<GroupResponse>("/groups", payload);
  return data;
};

export const useCreateGroup = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: createGroup,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: groupQueryKeys.list });
    },
  });
};
