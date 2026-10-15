import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { UserResponse } from "@/features/auth";
import { groupQueryKeys } from "./query-keys";

export const listGroupMembers = async (groupId: string): Promise<UserResponse[]> => {
  const { data } = await apiClient.get<UserResponse[]>(`/groups/${groupId}/members`);
  return data;
};

export const useGroupMembers = (groupId: string) =>
  useQuery({
    queryKey: groupQueryKeys.members(groupId),
    queryFn: () => listGroupMembers(groupId),
    // MembershipEditor stays mounted with no group selected between opens,
    // so an empty id must not fire -- it would hit /groups//members.
    enabled: groupId !== "",
  });
