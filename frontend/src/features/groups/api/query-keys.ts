export const groupQueryKeys = {
  list: ["admin-groups"] as const,
  members: (groupId: string) => ["admin-groups", groupId, "members"] as const,
  acl: (groupId: string) => ["admin-groups", groupId, "acl"] as const,
};

export const aclQueryKeys = {
  effective: (resourceType: string, resourceId: string) =>
    ["acl-effective", resourceType, resourceId] as const,
};
