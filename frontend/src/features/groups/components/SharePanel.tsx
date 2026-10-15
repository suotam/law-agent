import { useState } from "react";
import { useTranslation } from "react-i18next";
import { X } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { useHasCapability } from "@/features/auth";
import { useUsers } from "@/features/users";
import { useDeleteAclEntry, useUpsertAclEntry } from "../api/acl-mutations";
import { useEffectiveAcl } from "../api/effective-acl";
import { useGroups } from "../api/list-groups";
import type { AclEntryResponse, AclPermission, AclPrincipalType, AclResourceType } from "../types";

type SharePanelProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  resourceType: AclResourceType;
  resourceId: string;
  resourceName: string;
};

const permissionKey = (permission: AclPermission) =>
  permission === "write" ? "groups.sharePermissionWrite" : "groups.sharePermissionRead";

export const SharePanel = ({
  open,
  onOpenChange,
  resourceType,
  resourceId,
  resourceName,
}: SharePanelProps) => {
  const { t } = useTranslation();
  const effective = useEffectiveAcl(resourceType, resourceId);
  const groups = useGroups();
  const users = useUsers();
  const upsert = useUpsertAclEntry();
  const remove = useDeleteAclEntry();
  const canShareGroups = useHasCapability("manage_groups");
  const canShareUsers = useHasCapability("manage_users");
  // `caller` starts undefined (the /auth/me query is still loading), so the
  // default can't be captured once at mount -- it's derived every render
  // instead, and only overridden once the caller actually picks a radio.
  const [chosenPrincipalType, setPrincipalType] = useState<AclPrincipalType | null>(null);
  const principalType: AclPrincipalType =
    chosenPrincipalType ?? (canShareGroups ? "group" : "user");
  const [principalId, setPrincipalId] = useState("");
  const [permission, setPermission] = useState<AclPermission>("read");

  // A caller without manage_groups shouldn't learn which groups have access
  // at all, not just be unable to edit that -- same for manage_users and
  // user grants. Applies to both own and inherited entries.
  const canSeeEntry = (entry: AclEntryResponse) =>
    entry.principal_type === "group" ? canShareGroups : canShareUsers;

  const principalLabel = (entry: AclEntryResponse) => {
    if (entry.principal_type === "group")
      return (
        (groups.data ?? []).find((group) => group.id === entry.principal_id)?.name ??
        entry.principal_id
      );
    return (
      (users.data ?? []).find((user) => user.id === entry.principal_id)?.email ?? entry.principal_id
    );
  };

  // Documents are read-only in the ACL model -- only folders can carry write grants.
  const permissionOptions =
    resourceType === "document" ? (["read"] as const) : (["read", "write"] as const);

  const candidates: { id: string; label: string }[] =
    principalType === "group"
      ? (groups.data ?? []).map((group) => ({ id: group.id, label: group.name }))
      : (users.data ?? []).map((user) => ({ id: user.id, label: user.email }));

  const handleAdd = () => {
    if (principalId === "") return;
    upsert.mutate({
      resource_type: resourceType,
      resource_id: resourceId,
      principal_type: principalType,
      principal_id: principalId,
      permission,
    });
    setPrincipalId("");
  };

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("groups.shareTitle", { name: resourceName })}</DialogTitle>
          <DialogDescription className="sr-only">
            {t("groups.shareTitle", { name: resourceName })}
          </DialogDescription>
        </DialogHeader>

        {effective.isPending ? (
          <Skeleton className="h-10 w-full" />
        ) : effective.isError ? (
          <p className="text-destructive text-sm">{t("groups.shareLoadError")}</p>
        ) : (
          <>
            <section aria-label={t("groups.shareInheritedHeading")}>
              <h2 className="text-sm font-medium">{t("groups.shareInheritedHeading")}</h2>
              <ul className="text-muted-foreground text-sm">
                {effective.data.inherited.filter(canSeeEntry).map((entry) => (
                  <li key={entry.id}>
                    {principalLabel(entry)} — {t(permissionKey(entry.permission))}
                  </li>
                ))}
              </ul>
            </section>

            <section aria-label={t("groups.shareOwnHeading")}>
              <h2 className="text-sm font-medium">{t("groups.shareOwnHeading")}</h2>
              {(() => {
                const visibleOwn = effective.data.own.filter(canSeeEntry);
                return visibleOwn.length === 0 ? (
                  <p className="text-muted-foreground text-sm">{t("groups.shareEmptyOwn")}</p>
                ) : (
                  <ul>
                    {visibleOwn.map((entry) => (
                      <li
                        key={entry.id}
                        className="flex items-center gap-2 text-sm"
                      >
                        <span className="min-w-0 flex-1 truncate">
                          {principalLabel(entry)} — {t(permissionKey(entry.permission))}
                        </span>
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label={t("groups.shareRemoveLabel", {
                            principal: principalLabel(entry),
                          })}
                          onClick={() => remove.mutate(entry)}
                        >
                          <X aria-hidden="true" />
                        </Button>
                      </li>
                    ))}
                  </ul>
                );
              })()}
            </section>

            <div className="flex flex-col gap-2 border-t pt-3">
              {canShareGroups && canShareUsers && (
                <fieldset className="flex gap-4 text-sm">
                  <legend className="sr-only">{t("groups.sharePrincipalTypeLabel")}</legend>
                  <label className="flex items-center gap-1">
                    <input
                      type="radio"
                      name="principal-type"
                      checked={principalType === "group"}
                      onChange={() => {
                        setPrincipalType("group");
                        setPrincipalId("");
                      }}
                    />
                    {t("groups.sharePrincipalTypeGroup")}
                  </label>
                  <label className="flex items-center gap-1">
                    <input
                      type="radio"
                      name="principal-type"
                      checked={principalType === "user"}
                      onChange={() => {
                        setPrincipalType("user");
                        setPrincipalId("");
                      }}
                    />
                    {t("groups.sharePrincipalTypeUser")}
                  </label>
                </fieldset>
              )}

              <Label htmlFor="share-principal">{t("groups.sharePrincipalLabel")}</Label>
              <select
                id="share-principal"
                value={principalId}
                onChange={(event) => setPrincipalId(event.target.value)}
                className="border-input h-9 w-full rounded-md border bg-transparent px-2.5 text-sm shadow-xs"
              >
                <option value="">{t("groups.sharePrincipalPlaceholder")}</option>
                {candidates.map((candidate) => (
                  <option
                    key={candidate.id}
                    value={candidate.id}
                  >
                    {candidate.label}
                  </option>
                ))}
              </select>

              <Label htmlFor="share-permission">{t("groups.sharePermissionLabel")}</Label>
              <select
                id="share-permission"
                value={permission}
                onChange={(event) => setPermission(event.target.value as AclPermission)}
                className="border-input h-9 w-full rounded-md border bg-transparent px-2.5 text-sm shadow-xs"
              >
                {permissionOptions.map((option) => (
                  <option
                    key={option}
                    value={option}
                  >
                    {t(permissionKey(option))}
                  </option>
                ))}
              </select>

              {resourceType === "folder" && <p role="note">{t("groups.shareCascadeWarning")}</p>}

              <Button
                type="button"
                onClick={handleAdd}
                disabled={principalId === ""}
              >
                {t("groups.shareAddConfirm")}
              </Button>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
};
