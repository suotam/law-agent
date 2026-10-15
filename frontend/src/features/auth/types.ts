export type RoleCapability = "manage_users" | "manage_groups" | "manage_org_files_structure";

export type RoleSummary = {
  id: string;
  name: string;
};

export type UserResponse = {
  id: string;
  email: string;
  role: RoleSummary;
  capabilities: RoleCapability[];
  is_superuser: boolean;
  is_active: boolean;
  created_at: string;
};

export type LoginRequest = {
  email: string;
  password: string;
};

export type LoginResponse = {
  access_token: string;
  token_type: string;
};
