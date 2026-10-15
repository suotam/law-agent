import { MoreHorizontal } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ChangePasswordDialog, useAuth, useHasCapability } from "@/features/auth";
import type { UserResponse } from "@/features/auth";
import type { RoleResponse } from "@/features/roles";
import { useRoles } from "@/features/roles";
import { Skeleton } from "@/components/ui/skeleton";
import { useUsers } from "../api/list-users";
import { useUpdateUserRole } from "../api/update-user-role";
import { useDeactivateUser } from "../api/deactivate-user";
import { useActivateUser } from "../api/activate-user";
import { ResetPasswordDialog } from "./ResetPasswordDialog";
import { UserGroupsDialog } from "./UserGroupsDialog";

const formatDate = (iso: string) => new Date(iso).toLocaleDateString("cs-CZ");

const canChangeRole = (caller: UserResponse, user: UserResponse, isOwn: boolean) => {
  if (isOwn || !user.is_active) return false;
  // A superuser account is superuser business: see the backend's
  // _assert_manageable, which is the authority this mirrors.
  if (user.is_superuser && !caller.is_superuser) return false;
  return true;
};

// Stricter than the backend's own guard (which lets one superuser manage
// another's account): a superuser's row menu is for that account holder
// alone, so nobody else -- including another superuser -- sees it.
const canManageAccount = (user: UserResponse, isOwn: boolean) => !isOwn && !user.is_superuser;

type RowMenuProps = {
  label: string;
  items: { key: string; label: string; onClick: () => void }[];
};

const RowMenu = ({ label, items }: RowMenuProps) => {
  const [open, setOpen] = useState(false);

  return (
    <Popover
      open={open}
      onOpenChange={setOpen}
    >
      <PopoverTrigger
        render={
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={label}
          >
            <MoreHorizontal aria-hidden="true" />
          </Button>
        }
      />
      <PopoverContent
        align="end"
        className="w-44 p-1"
      >
        {items.map((item) => (
          <Button
            key={item.key}
            variant="ghost"
            role="menuitem"
            className="w-full justify-start"
            onClick={() => {
              setOpen(false);
              item.onClick();
            }}
          >
            {item.label}
          </Button>
        ))}
      </PopoverContent>
    </Popover>
  );
};

// The current role must always be an option, even one the caller can't pick
// (e.g. superuser), or the select falls back to displaying whichever option
// happens to be first.
const withCurrentRole = (
  roleOptions: RoleResponse[],
  currentRole: { id: string; name: string },
): { id: string; name: string }[] =>
  roleOptions.some((role) => role.id === currentRole.id)
    ? roleOptions
    : [...roleOptions, currentRole];

type UserRowProps = {
  user: UserResponse;
  caller: UserResponse;
  roleOptions: RoleResponse[];
  onRoleChange: (roleId: string) => void;
  isUpdating: boolean;
  onDeactivate: () => void;
  onReactivate: () => void;
  onResetPassword: () => void;
  onChangeOwnPassword: () => void;
  onEditGroups: () => void;
};

const UserRow = ({
  user,
  caller,
  roleOptions,
  onRoleChange,
  isUpdating,
  onDeactivate,
  onReactivate,
  onResetPassword,
  onChangeOwnPassword,
  onEditGroups,
}: UserRowProps) => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const hasManageUsers = useHasCapability("manage_users");
  const hasManageGroups = useHasCapability("manage_groups");
  const hasStructureCapability = useHasCapability("manage_org_files_structure");
  const isOwn = user.id === caller.id;
  const manageable = canManageAccount(user, isOwn);
  const roleEditable = canChangeRole(caller, user, isOwn);
  // A superuser bypasses ACL entirely (see ARCHITECTURE.md), so per-user
  // file access is meaningless for their own account -- never offered, even
  // to themselves.
  const canViewAccess = !user.is_superuser && hasManageUsers && hasStructureCapability;
  // Editing group membership touches both domains (members of groups and of
  // users), so the caller needs both capabilities -- and the superuser row
  // boundary applies, mirroring the backend's _assert_manageable.
  const canEditGroups = manageable && hasManageUsers && hasManageGroups;
  const accessMenuItem = {
    key: "access",
    label: t("users.accessLabel"),
    onClick: () => navigate(`/admin/users/${user.id}/access`),
  };
  const groupsMenuItem = {
    key: "groups",
    label: t("users.groupsLabel"),
    onClick: onEditGroups,
  };
  // Account-management items stay gated exactly as before (isOwn/manageable);
  // the access item has its own, independent gate (canViewAccess), so a
  // caller who can view access but not manage this account still gets a menu
  // with only that item, not the account-management ones.
  const baseMenuItems =
    isOwn || manageable
      ? isOwn
        ? [
            {
              key: "change-password",
              label: t("users.changePassword"),
              onClick: onChangeOwnPassword,
            },
          ]
        : user.is_active
          ? [
              { key: "reset-password", label: t("users.resetPassword"), onClick: onResetPassword },
              { key: "deactivate", label: t("users.deactivate"), onClick: onDeactivate },
            ]
          : [{ key: "reactivate", label: t("users.reactivate"), onClick: onReactivate }]
      : [];
  const capabilityGatedItems = [
    ...(canViewAccess ? [accessMenuItem] : []),
    ...(canEditGroups ? [groupsMenuItem] : []),
  ];
  const menuItems = [...capabilityGatedItems, ...baseMenuItems];

  return (
    <li className="border-border flex items-center gap-3 border-b px-3 py-2 text-sm last:border-b-0">
      <span className="min-w-0 flex-1 truncate">{user.email}</span>
      {!user.is_active && (
        <span className="text-muted-foreground shrink-0">{t("users.deactivated")}</span>
      )}
      <span className="text-muted-foreground w-28 shrink-0">{formatDate(user.created_at)}</span>
      {user.is_active && (
        <select
          aria-label={t("users.roleSelectLabel", { email: user.email })}
          value={user.role.id}
          disabled={!roleEditable || isUpdating}
          onChange={(event) => onRoleChange(event.target.value)}
          className="border-input h-9 w-40 shrink-0 rounded-md border bg-transparent px-2.5 text-sm shadow-xs disabled:opacity-50"
        >
          {withCurrentRole(roleOptions, user.role).map((role) => (
            <option
              key={role.id}
              value={role.id}
            >
              {role.name}
            </option>
          ))}
        </select>
      )}
      {menuItems.length > 0 && (
        <RowMenu
          label={t("users.rowActionsLabel", { email: user.email })}
          items={menuItems}
        />
      )}
    </li>
  );
};

export const UserTable = () => {
  const { t } = useTranslation();
  const users = useUsers();
  const roles = useRoles();
  const updateRole = useUpdateUserRole();
  const deactivate = useDeactivateUser();
  const activate = useActivateUser();
  const { user: caller } = useAuth();
  const [resetTarget, setResetTarget] = useState<UserResponse | null>(null);
  const [groupsTarget, setGroupsTarget] = useState<UserResponse | null>(null);
  const [isOwnPasswordOpen, setIsOwnPasswordOpen] = useState(false);

  if (users.isPending || roles.isPending || caller === undefined)
    return (
      <div className="flex flex-col gap-2">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
      </div>
    );

  if (users.isError || roles.isError)
    return <p className="text-destructive text-sm">{t("users.loadError")}</p>;

  // The superuser role is handed out by superusers only -- the same rule the
  // backend enforces, so a manager simply never sees it as a choice.
  const selectableRoles = caller.is_superuser
    ? roles.data
    : roles.data.filter((role) => !role.is_superuser);

  return (
    <>
      <ul className="border-border divide-border rounded-md border">
        {users.data.map((user) => (
          <UserRow
            key={user.id}
            user={user}
            caller={caller}
            roleOptions={selectableRoles}
            onRoleChange={(roleId) => updateRole.mutate({ id: user.id, role_id: roleId })}
            isUpdating={updateRole.isPending && updateRole.variables.id === user.id}
            onDeactivate={() => deactivate.mutate(user.id)}
            onReactivate={() => activate.mutate(user.id)}
            onResetPassword={() => setResetTarget(user)}
            onChangeOwnPassword={() => setIsOwnPasswordOpen(true)}
            onEditGroups={() => setGroupsTarget(user)}
          />
        ))}
      </ul>
      <ResetPasswordDialog
        userId={resetTarget?.id ?? ""}
        email={resetTarget?.email ?? ""}
        open={resetTarget !== null}
        onOpenChange={(open) => {
          if (!open) setResetTarget(null);
        }}
      />
      <UserGroupsDialog
        user={groupsTarget}
        open={groupsTarget !== null}
        onOpenChange={(open) => {
          if (!open) setGroupsTarget(null);
        }}
      />
      <ChangePasswordDialog
        open={isOwnPasswordOpen}
        onOpenChange={setIsOwnPasswordOpen}
      />
    </>
  );
};
