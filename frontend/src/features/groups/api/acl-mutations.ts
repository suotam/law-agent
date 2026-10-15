import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { userQueryKeys } from "@/features/users";
import type { AclEntryResponse, AclPermission, AclPrincipalType, AclResourceType } from "../types";
import { aclQueryKeys, groupQueryKeys } from "./query-keys";

type UpsertAclEntryRequest = {
  resource_type: AclResourceType;
  resource_id: string;
  principal_type: AclPrincipalType;
  principal_id: string;
  permission: AclPermission;
};

export const upsertAclEntry = async (payload: UpsertAclEntryRequest): Promise<AclEntryResponse> => {
  const { data } = await apiClient.post<AclEntryResponse>("/acl", payload);
  return data;
};

export const deleteAclEntry = async (id: string): Promise<void> => {
  await apiClient.delete(`/acl/${id}`);
};

type AclCacheKey = {
  resource_type: AclResourceType;
  resource_id: string;
  principal_type: AclPrincipalType;
  principal_id: string;
};

/** Invalidates every query an ACL write could affect: both callers' caches
 * (group-centric and resource-centric) plus the effective-acl view.
 *
 * Only the exact written resource's `effective` query is invalidated, not its
 * descendants' -- a grant on a folder does not walk the tree to refresh every
 * child's already-open Share panel. Acceptable staleness: reopening the panel
 * (a fresh `useEffectiveAcl` mount) always resolves against the live data. */
const invalidateAclCaches = async (
  queryClient: ReturnType<typeof useQueryClient>,
  entry: AclCacheKey,
) => {
  await queryClient.invalidateQueries({
    queryKey: aclQueryKeys.effective(entry.resource_type, entry.resource_id),
  });
  if (entry.principal_type === "group") {
    await queryClient.invalidateQueries({ queryKey: groupQueryKeys.acl(entry.principal_id) });
  } else {
    await queryClient.invalidateQueries({ queryKey: userQueryKeys.acl(entry.principal_id) });
  }
};

export const useUpsertAclEntry = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: upsertAclEntry,
    onSuccess: (entry) => invalidateAclCaches(queryClient, entry),
  });
};

export const useDeleteAclEntry = () => {
  const queryClient = useQueryClient();

  return useMutation({
    // The caller passes the whole entry, not just the id, so the cache
    // invalidation above knows which queries were affected.
    mutationFn: (entry: AclEntryResponse) => deleteAclEntry(entry.id).then(() => entry),
    onSuccess: (entry) => invalidateAclCaches(queryClient, entry),
  });
};
