import { useTranslation } from "react-i18next";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { useGroups } from "@/features/groups";
import type { UserResponse } from "@/features/auth";
import { useSetUserMembership } from "../api/set-user-membership";
import { useUserGroups } from "../api/list-user-groups";

type UserGroupsDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  user: UserResponse | null;
};

export const UserGroupsDialog = ({ open, onOpenChange, user }: UserGroupsDialogProps) => {
  const { t } = useTranslation();
  const userId = user?.id ?? "";
  const groups = useGroups();
  const memberships = useUserGroups(userId);
  const setMembership = useSetUserMembership(userId);

  if (user === null) return null;

  const memberIds = new Set((memberships.data ?? []).map((membership) => membership.id));
  // Rows derive from the groups list, not from the membership response: the
  // optimistic insert only knows the id, so names must come from one place.
  const memberGroups = (groups.data ?? []).filter((group) => memberIds.has(group.id));
  const candidates = (groups.data ?? []).filter((group) => !memberIds.has(group.id));

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("users.groupsTitle", { email: user.email })}</DialogTitle>
          <DialogDescription className="sr-only">
            {t("users.groupsTitle", { email: user.email })}
          </DialogDescription>
        </DialogHeader>

        {groups.isPending || memberships.isPending ? (
          <Skeleton className="h-10 w-full" />
        ) : groups.isError || memberships.isError ? (
          <p className="text-destructive text-sm">{t("users.groupsLoadError")}</p>
        ) : memberGroups.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("users.groupsEmpty")}</p>
        ) : (
          <ul className="border-border divide-border my-2 rounded-md border">
            {memberGroups.map((group) => (
              <li
                key={group.id}
                className="border-border flex items-center gap-2 border-b px-3 py-1 text-sm last:border-b-0"
              >
                <span className="min-w-0 flex-1 truncate">{group.name}</span>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={t("users.removeGroupLabel", { name: group.name })}
                  onClick={() => setMembership.mutate({ groupId: group.id, member: false })}
                >
                  <X aria-hidden="true" />
                </Button>
              </li>
            ))}
          </ul>
        )}

        <div className="flex flex-col gap-2">
          <Label htmlFor="add-group">{t("users.addGroupLabel")}</Label>
          <select
            id="add-group"
            value=""
            onChange={(event) => {
              if (event.target.value !== "")
                setMembership.mutate({ groupId: event.target.value, member: true });
            }}
            className="border-input h-9 w-full rounded-md border bg-transparent px-2.5 text-sm shadow-xs"
          >
            <option value="">{t("users.addGroupPlaceholder")}</option>
            {candidates.map((candidate) => (
              <option
                key={candidate.id}
                value={candidate.id}
              >
                {candidate.name}
              </option>
            ))}
          </select>
        </div>
      </DialogContent>
    </Dialog>
  );
};
