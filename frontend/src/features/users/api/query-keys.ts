export const userQueryKeys = {
  list: ["admin-users"] as const,
  acl: (userId: string) => ["admin-users", userId, "acl"] as const,
  groups: (userId: string) => ["admin-users", userId, "groups"] as const,
};
