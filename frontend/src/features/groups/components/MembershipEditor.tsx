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
import { useUsers } from "@/features/users";
import { useAddGroupMember } from "../api/add-group-member";
import { useGroupMembers } from "../api/list-group-members";
import { useRemoveGroupMember } from "../api/remove-group-member";
import type { GroupResponse } from "../types";

type MembershipEditorProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  group: GroupResponse | null;
};

export const MembershipEditor = ({ open, onOpenChange, group }: MembershipEditorProps) => {
  const { t } = useTranslation();
  const groupId = group?.id ?? "";
  const members = useGroupMembers(groupId);
  const allUsers = useUsers();
  const addMember = useAddGroupMember(groupId);
  const removeMember = useRemoveGroupMember(groupId);

  if (group === null) return null;

  const memberIds = new Set((members.data ?? []).map((member) => member.id));
  const candidates = (allUsers.data ?? []).filter((candidate) => !memberIds.has(candidate.id));

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("groups.membersTitle", { name: group.name })}</DialogTitle>
          <DialogDescription className="sr-only">
            {t("groups.membersTitle", { name: group.name })}
          </DialogDescription>
        </DialogHeader>

        {members.isPending ? (
          <Skeleton className="h-10 w-full" />
        ) : members.isError ? (
          <p className="text-destructive text-sm">{t("groups.membersLoadError")}</p>
        ) : members.data.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("groups.membersEmpty")}</p>
        ) : (
          <ul className="border-border divide-border my-2 rounded-md border">
            {members.data.map((member) => (
              <li
                key={member.id}
                className="border-border flex items-center gap-2 border-b px-3 py-1 text-sm last:border-b-0"
              >
                <span className="min-w-0 flex-1 truncate">{member.email}</span>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={t("groups.removeMemberLabel", { email: member.email })}
                  onClick={() => removeMember.mutate(member.id)}
                >
                  <X aria-hidden="true" />
                </Button>
              </li>
            ))}
          </ul>
        )}

        <div className="flex flex-col gap-2">
          <Label htmlFor="add-member">{t("groups.addMemberLabel")}</Label>
          <select
            id="add-member"
            value=""
            onChange={(event) => {
              if (event.target.value !== "") addMember.mutate(event.target.value);
            }}
            className="border-input h-9 w-full rounded-md border bg-transparent px-2.5 text-sm shadow-xs"
          >
            <option value="">{t("groups.addMemberPlaceholder")}</option>
            {candidates.map((candidate) => (
              <option
                key={candidate.id}
                value={candidate.id}
              >
                {candidate.email}
              </option>
            ))}
          </select>
        </div>
      </DialogContent>
    </Dialog>
  );
};
