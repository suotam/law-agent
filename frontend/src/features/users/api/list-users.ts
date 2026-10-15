import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { UserResponse } from "@/features/auth";
import { userQueryKeys } from "./query-keys";

export const listUsers = async (): Promise<UserResponse[]> => {
  const { data } = await apiClient.get<UserResponse[]>("/users");
  return data;
};

export const useUsers = () =>
  useQuery({
    queryKey: userQueryKeys.list,
    queryFn: listUsers,
  });
