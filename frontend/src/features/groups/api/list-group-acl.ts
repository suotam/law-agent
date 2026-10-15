import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { AclBrowseResponse } from "../types";
import { groupQueryKeys } from "./query-keys";

export const listGroupAcl = async (groupId: string): Promise<AclBrowseResponse> => {
  const { data } = await apiClient.get<AclBrowseResponse>(`/groups/${groupId}/acl`);
  return data;
};

/** Fetched once for the whole tree the group-centric browser navigates,
 * not per visited row -- matches the backend's rationale for this endpoint. */
export const useGroupAcl = (groupId: string) =>
  useQuery({
    queryKey: groupQueryKeys.acl(groupId),
    queryFn: () => listGroupAcl(groupId),
    // Callers fall back to "" for a not-yet-resolved route param -- never
    // fetch on that, it would hit /groups//acl.
    enabled: groupId !== "",
  });
