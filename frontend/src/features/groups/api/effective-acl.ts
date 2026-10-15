import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { AclEffectiveResponse, AclResourceType } from "../types";
import { aclQueryKeys } from "./query-keys";

export const getEffectiveAcl = async (
  resourceType: AclResourceType,
  resourceId: string,
): Promise<AclEffectiveResponse> => {
  const { data } = await apiClient.get<AclEffectiveResponse>("/acl/effective", {
    params: { resource_type: resourceType, resource_id: resourceId },
  });
  return data;
};

export const useEffectiveAcl = (resourceType: AclResourceType, resourceId: string) =>
  useQuery({
    queryKey: aclQueryKeys.effective(resourceType, resourceId),
    queryFn: () => getEffectiveAcl(resourceType, resourceId),
  });
