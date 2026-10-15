import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { GroupResponse } from "../types";
import { groupQueryKeys } from "./query-keys";

export const listGroups = async (): Promise<GroupResponse[]> => {
  const { data } = await apiClient.get<GroupResponse[]>("/groups");
  return data;
};

export const useGroups = () =>
  useQuery({
    queryKey: groupQueryKeys.list,
    queryFn: listGroups,
  });
