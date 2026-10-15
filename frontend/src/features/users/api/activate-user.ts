import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { UserResponse } from "@/features/auth";
import { userQueryKeys } from "./query-keys";

export const useActivateUser = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (id: string): Promise<UserResponse> => {
      const { data } = await apiClient.post<UserResponse>(`/users/${id}/activate`);
      return data;
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: userQueryKeys.list });
    },
  });
};
