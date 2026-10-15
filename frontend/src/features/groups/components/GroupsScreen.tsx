import { useState } from "react";
import type { ParseKeys } from "i18next";
import { Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { useDeleteGroup } from "../api/delete-group";
import { CreateGroupDialog } from "./CreateGroupDialog";
import { RenameGroupDialog } from "./RenameGroupDialog";
import { DeleteGroupDialog } from "./DeleteGroupDialog";
import { GroupTable } from "./GroupTable";
import { MembershipEditor } from "./MembershipEditor";
import type { GroupResponse } from "../types";

export const GroupsScreen = () => {
  const { t } = useTranslation();
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [renameTarget, setRenameTarget] = useState<GroupResponse | null>(null);
  const [membersTarget, setMembersTarget] = useState<GroupResponse | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<GroupResponse | null>(null);
  const [deleteErrorKey, setDeleteErrorKey] = useState<ParseKeys | null>(null);
  const deleteGroup = useDeleteGroup();

  const closeDelete = () => {
    setDeleteTarget(null);
    setDeleteErrorKey(null);
  };

  const confirmDelete = async () => {
    if (deleteTarget === null) return;
    setDeleteErrorKey(null);

    try {
      await deleteGroup.mutateAsync(deleteTarget.id);
      closeDelete();
    } catch {
      setDeleteErrorKey("groups.deleteFailed");
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 p-4">
      <div className="flex items-center justify-between gap-2">
        <h1 className="text-lg font-semibold tracking-tight">{t("groups.heading")}</h1>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => setIsCreateOpen(true)}
        >
          <Plus aria-hidden="true" />
          {t("groups.newGroup")}
        </Button>
      </div>

      <GroupTable
        onRename={setRenameTarget}
        onDelete={setDeleteTarget}
        onEditMembers={setMembersTarget}
      />

      <CreateGroupDialog
        open={isCreateOpen}
        onOpenChange={setIsCreateOpen}
      />

      <RenameGroupDialog
        open={renameTarget !== null}
        onOpenChange={(isOpen) => !isOpen && setRenameTarget(null)}
        group={renameTarget}
      />

      <MembershipEditor
        open={membersTarget !== null}
        onOpenChange={(isOpen) => !isOpen && setMembersTarget(null)}
        group={membersTarget}
      />

      <DeleteGroupDialog
        open={deleteTarget !== null}
        onOpenChange={(isOpen) => !isOpen && closeDelete()}
        errorMessage={deleteErrorKey === null ? null : t(deleteErrorKey)}
        isPending={deleteGroup.isPending}
        onConfirm={() => void confirmDelete()}
      />
    </div>
  );
};
