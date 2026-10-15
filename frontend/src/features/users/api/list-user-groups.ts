import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { GroupResponse } from "@/features/groups";
import { userQueryKeys } from "./query-keys";

export const listUserGroups = async (userId: string): Promise<GroupResponse[]> => {
  const { data } = await apiClient.get<GroupResponse[]>(`/users/${userId}/groups`);
  return data;
};

export const useUserGroups = (userId: string) =>
  useQuery({
    queryKey: userQueryKeys.groups(userId),
    queryFn: () => listUserGroups(userId),
    // Callers fall back to "" for a not-yet-resolved route param -- never
    // fetch on that, it would hit /users//groups.
    enabled: userId !== "",
  });
