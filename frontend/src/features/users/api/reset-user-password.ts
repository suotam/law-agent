import { useMutation } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";

type ResetUserPasswordRequest = {
  id: string;
  new_password: string;
};

export const useResetUserPassword = () =>
  useMutation({
    // No cache invalidation: the password is not part of any query's data.
    mutationFn: async ({ id, new_password }: ResetUserPasswordRequest) => {
      await apiClient.put(`/users/${id}/password`, { new_password });
    },
  });
