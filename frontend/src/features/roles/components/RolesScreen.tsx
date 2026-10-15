import { useState } from "react";
import type { ParseKeys } from "i18next";
import { Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { translateError } from "@/lib/errors";
import { useDeleteRole } from "../api/delete-role";
import { useRoles } from "../api/list-roles";
import { DeleteRoleDialog } from "./DeleteRoleDialog";
import { RoleDialog } from "./RoleDialog";
import { RoleTable } from "./RoleTable";
import type { RoleResponse } from "../types";

export const RolesScreen = () => {
  const { t } = useTranslation();
  const roles = useRoles();
  const [dialogState, setDialogState] = useState<{ open: boolean; roleId: string | null }>({
    open: false,
    roleId: null,
  });
  // Looked up by id on every render, rather than stashing the row object at
  // open time, so a capability toggle's list refetch keeps the open dialog's
  // checkboxes in sync instead of freezing them at the moment it was opened.
  const role =
    dialogState.roleId === null
      ? null
      : (roles.data?.find((r) => r.id === dialogState.roleId) ?? null);
  const [deleteTarget, setDeleteTarget] = useState<RoleResponse | null>(null);
  const [deleteErrorKey, setDeleteErrorKey] = useState<ParseKeys | null>(null);
  const deleteRole = useDeleteRole();

  const closeDelete = () => {
    setDeleteTarget(null);
    setDeleteErrorKey(null);
  };

  const confirmDelete = async () => {
    if (deleteTarget === null) return;
    setDeleteErrorKey(null);

    try {
      await deleteRole.mutateAsync(deleteTarget.id);
      closeDelete();
    } catch (error) {
      // A 409 on a role means only one thing here: it is still assigned to a user.
      setDeleteErrorKey(
        translateError(error).status === 409 ? "roles.deleteInUse" : "roles.deleteFailed",
      );
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 p-4">
      <div className="flex items-center justify-between gap-2">
        <h1 className="text-lg font-semibold tracking-tight">{t("roles.heading")}</h1>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => setDialogState({ open: true, roleId: null })}
        >
          <Plus aria-hidden="true" />
          {t("roles.newRole")}
        </Button>
      </div>

      <RoleTable
        onEdit={(role) => setDialogState({ open: true, roleId: role.id })}
        onDelete={setDeleteTarget}
      />

      <RoleDialog
        open={dialogState.open}
        onOpenChange={(isOpen) => setDialogState((current) => ({ ...current, open: isOpen }))}
        role={role}
      />

      <DeleteRoleDialog
        open={deleteTarget !== null}
        onOpenChange={(isOpen) => !isOpen && closeDelete()}
        errorMessage={deleteErrorKey === null ? null : t(deleteErrorKey)}
        isPending={deleteRole.isPending}
        onConfirm={() => void confirmDelete()}
      />
    </div>
  );
};
