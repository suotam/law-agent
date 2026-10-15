import type { RoleCapability } from "@/features/auth";

export const ROLE_CAPABILITIES: readonly RoleCapability[] = [
  "manage_users",
  "manage_groups",
  "manage_org_files_structure",
];

export type RoleResponse = {
  id: string;
  name: string;
  is_superuser: boolean;
  capabilities: RoleCapability[];
  created_at: string;
};
