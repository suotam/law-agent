import type { UserResponse } from "@/features/auth";

export type GroupResponse = {
  id: string;
  name: string;
  created_at: string;
};

export type AclResourceType = "folder" | "document";
export type AclPrincipalType = "group" | "user";
export type AclPermission = "read" | "write";

export type AclEntryResponse = {
  id: string;
  resource_type: AclResourceType;
  resource_id: string;
  principal_type: AclPrincipalType;
  principal_id: string;
  permission: AclPermission;
  created_at: string;
};

export type AclEffectiveResponse = {
  own: AclEntryResponse[];
  inherited: AclEntryResponse[];
};

export type AclBrowseResponse = {
  entries: AclEntryResponse[];
  folders_with_nested_grant: string[];
};

/** Re-exported so `features/groups` consumers don't reach into `features/auth`
 * just to type a member list. */
export type GroupMember = UserResponse;
