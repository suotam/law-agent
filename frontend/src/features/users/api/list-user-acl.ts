import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { AclBrowseResponse } from "@/features/groups";
import { userQueryKeys } from "./query-keys";

export const listUserAcl = async (userId: string): Promise<AclBrowseResponse> => {
  const { data } = await apiClient.get<AclBrowseResponse>(`/users/${userId}/acl`);
  return data;
};

/** Fetched once for the whole tree the per-user browser navigates, mirroring
 * `useGroupAcl` -- see its comment for why this isn't per-visited-row. */
export const useUserAcl = (userId: string) =>
  useQuery({
    queryKey: userQueryKeys.acl(userId),
    queryFn: () => listUserAcl(userId),
    // Callers fall back to "" for a not-yet-resolved route param -- never
    // fetch on that, it would hit /users//acl.
    enabled: userId !== "",
  });
