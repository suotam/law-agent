import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { UserResponse } from "@/features/auth";
import { userQueryKeys } from "./query-keys";

type CreateUserRequest = {
  email: string;
  password: string;
  role_id: string;
};

export const createUser = async (payload: CreateUserRequest): Promise<UserResponse> => {
  const { data } = await apiClient.post<UserResponse>("/users", payload);
  return data;
};

export const useCreateUser = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: createUser,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: userQueryKeys.list });
    },
  });
};
