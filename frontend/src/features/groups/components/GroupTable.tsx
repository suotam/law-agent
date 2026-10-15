import { useTranslation } from "react-i18next";
import { Link } from "react-router";
import { FolderLock, Pencil, Trash2, Users as UsersIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useHasCapability } from "@/features/auth";
import { useGroups } from "../api/list-groups";
import type { GroupResponse } from "../types";

type GroupTableProps = {
  onRename?: (group: GroupResponse) => void;
  onDelete?: (group: GroupResponse) => void;
  onEditMembers?: (group: GroupResponse) => void;
};

export const GroupTable = ({ onRename, onDelete, onEditMembers }: GroupTableProps) => {
  const { t } = useTranslation();
  const groups = useGroups();
  // Editing a group's access grants requires manage_org_files_structure too
  // (see router.tsx) -- manage_groups alone (which this whole screen is
  // already gated on) isn't enough to reach that route.
  const canViewAccess = useHasCapability("manage_org_files_structure");

  if (groups.isPending)
    return (
      <div className="flex flex-col gap-2">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
      </div>
    );

  if (groups.isError) return <p className="text-destructive text-sm">{t("groups.loadError")}</p>;

  return (
    <ul className="border-border divide-border rounded-md border">
      {groups.data.map((group) => (
        <li
          key={group.id}
          className="border-border flex items-center gap-3 border-b px-3 py-2 text-sm last:border-b-0"
        >
          <span className="min-w-0 flex-1 truncate font-medium">{group.name}</span>

          <div className="ml-auto flex shrink-0 items-center gap-1">
            {onEditMembers && (
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={t("groups.membersLabel", { name: group.name })}
                onClick={() => onEditMembers(group)}
              >
                <UsersIcon aria-hidden="true" />
              </Button>
            )}
            {canViewAccess && (
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={t("groups.accessLabel", { name: group.name })}
                render={<Link to={`/admin/groups/${group.id}/access`} />}
              >
                <FolderLock aria-hidden="true" />
              </Button>
            )}
            {onRename && (
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={t("groups.renameLabel", { name: group.name })}
                onClick={() => onRename(group)}
              >
                <Pencil aria-hidden="true" />
              </Button>
            )}
            {onDelete && (
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={t("groups.deleteLabel", { name: group.name })}
                onClick={() => onDelete(group)}
              >
                <Trash2 aria-hidden="true" />
              </Button>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
};
