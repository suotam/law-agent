import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { RoleResponse } from "../types";
import { roleQueryKeys } from "./query-keys";

export const listRoles = async (): Promise<RoleResponse[]> => {
  const { data } = await apiClient.get<RoleResponse[]>("/roles");
  return data;
};

export const useRoles = () =>
  useQuery({
    queryKey: roleQueryKeys.list,
    queryFn: listRoles,
  });
