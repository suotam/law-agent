import { useEffect, useMemo, useState } from "react";
import { Circle, Eye, SquarePen } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Breadcrumb } from "@/features/org-files/components/Breadcrumb";
import { ItemList } from "@/features/org-files/components/ItemList";
import { useFolderLevel } from "@/features/org-files/api/get-folders";
import { useFolderPath } from "@/features/org-files/path";
import type { FolderItem, OrgFileResponse } from "@/features/org-files/types";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { useUpsertAclEntry, useDeleteAclEntry } from "../api/acl-mutations";
import type {
  AclBrowseResponse,
  AclEntryResponse,
  AclPrincipalType,
  AclResourceType,
} from "../types";

/** The three states a resource's own grant can cycle through by clicking
 * its indicator: no grant, read, write -- in that order, wrapping back to
 * none. Mirrors the backend's two-permission model plus "no grant at all". */
type AccessLevel = "none" | "read" | "write";

const FOLDER_NEXT_LEVEL: Record<AccessLevel, AccessLevel> = {
  none: "read",
  read: "write",
  write: "none",
};

// Documents only ever support a "read" grant on the backend (see SharePanel's
// same read-only rule for Decision 7) -- so their cycle skips "write"
// entirely. A document should never actually be in "write" state after the
// grants migration, but "write" is mapped to "none" too so a row can't get
// stuck if that assumption is ever wrong.
const DOCUMENT_NEXT_LEVEL: Record<AccessLevel, AccessLevel> = {
  none: "read",
  read: "none",
  write: "none",
};

const nextLevel = (current: AccessLevel, resourceType: AclResourceType): AccessLevel =>
  resourceType === "document" ? DOCUMENT_NEXT_LEVEL[current] : FOLDER_NEXT_LEVEL[current];

const LEVEL_ICON: Record<AccessLevel, typeof Circle> = {
  none: Circle,
  read: Eye,
  write: SquarePen,
};

const LEVEL_COLOR: Record<AccessLevel, string> = {
  none: "text-muted-foreground",
  read: "text-blue-600 dark:text-blue-400",
  write: "text-orange-600 dark:text-orange-400",
};

const levelOf = (entry: AclEntryResponse | undefined): AccessLevel => entry?.permission ?? "none";

type AclQueryResult = {
  data: AclBrowseResponse | undefined;
  isPending: boolean;
  isError: boolean;
};

type AccessBrowserProps = {
  principalType: AclPrincipalType;
  principalId: string;
  principalName: string;
  acl: AclQueryResult;
};

/** Resolves one ancestor folder's name for the "via <name>" inherited label,
 * the same per-level lookup `BreadcrumbSegment` does -- reusing the cached
 * `useFolderLevel(parentId)` query rather than adding a new endpoint. */
const AncestorNameProbe = ({
  parentId,
  folderId,
  onResolved,
}: {
  parentId: string | null;
  folderId: string;
  onResolved: (name: string) => void;
}) => {
  const { data } = useFolderLevel(parentId);
  const name = data?.folders.find((item) => item.id === folderId)?.name;

  useEffect(() => {
    if (name !== undefined) onResolved(name);
  }, [name, onResolved]);

  return null;
};

const byName = <T,>(items: T[], nameOf: (item: T) => string): T[] =>
  [...items].sort((a, b) => nameOf(a).localeCompare(nameOf(b), "cs"));

export const AccessBrowser = ({
  principalType,
  principalId,
  principalName,
  acl,
}: AccessBrowserProps) => {
  const { t } = useTranslation();
  const { pathIds, folderId, open, goToLevel } = useFolderPath();
  const level = useFolderLevel(folderId);
  const upsert = useUpsertAclEntry();
  const remove = useDeleteAclEntry();
  const [ancestorNames, setAncestorNames] = useState<Record<string, string>>({});

  const grantsByResource = useMemo(() => {
    const map = new Map<string, AclEntryResponse>();
    for (const entry of acl.data?.entries ?? [])
      map.set(`${entry.resource_type}:${entry.resource_id}`, entry);
    return map;
  }, [acl.data]);

  // Folders with nothing of their own or inherited, but something granted
  // deeper inside -- computed server-side, since it needs the whole subtree.
  const foldersWithNestedGrant = useMemo(
    () => new Set(acl.data?.folders_with_nested_grant ?? []),
    [acl.data],
  );

  // The nearest ancestor folder (closest to the current level first) that has
  // its own grant -- that grant is what a child with no grant of its own inherits.
  const inheritedFrom = useMemo(() => {
    for (let index = pathIds.length - 1; index >= 0; index -= 1) {
      const ancestorId = pathIds[index];
      if (grantsByResource.has(`folder:${ancestorId}`)) return ancestorId;
    }
    return null;
  }, [pathIds, grantsByResource]);

  const cycleAccess = (resourceType: AclResourceType, id: string, current: AccessLevel) => {
    const key = `${resourceType}:${id}`;
    const existing = grantsByResource.get(key);
    const next = nextLevel(current, resourceType);

    if (next === "none") {
      if (existing !== undefined) remove.mutate(existing);
      return;
    }
    upsert.mutate({
      resource_type: resourceType,
      resource_id: id,
      principal_type: principalType,
      principal_id: principalId,
      permission: next,
    });
  };

  const renderToggle = (resourceType: AclResourceType, id: string, name: string) => {
    const own = grantsByResource.get(`${resourceType}:${id}`);
    // Inheritance flows to documents exactly like it does to child folders --
    // the backend's ancestor chain doesn't special-case resource type either.
    const isInheritedHere = own === undefined && inheritedFrom !== null;
    const inheritedEntry = isInheritedHere
      ? grantsByResource.get(`folder:${inheritedFrom}`)
      : undefined;
    const level = own !== undefined ? levelOf(own) : levelOf(inheritedEntry);
    const Icon = LEVEL_ICON[level];
    const stateLabel = t(`access.level.${level}`);
    // Independent of inherited state -- a folder can both inherit a grant
    // from an ancestor and separately contain one of its own somewhere
    // deeper inside; each is worth showing.
    const hasNestedGrant =
      resourceType === "folder" && own === undefined && foldersWithNestedGrant.has(id);

    return (
      <div className="flex shrink-0 items-center gap-2">
        {isInheritedHere && (
          <span className="text-muted-foreground text-xs">
            {t("access.inheritedLabel", { folder: ancestorNames[inheritedFrom] ?? "" })}
          </span>
        )}
        {hasNestedGrant && (
          <span className="text-muted-foreground text-xs">{t("access.nestedGrantLabel")}</span>
        )}
        <button
          type="button"
          aria-label={t("access.toggleLabel", { name, state: stateLabel })}
          title={stateLabel}
          disabled={isInheritedHere}
          onClick={() => cycleAccess(resourceType, id, level)}
          className={cn(
            "rounded-sm p-1 transition-opacity hover:opacity-70 disabled:opacity-50 disabled:hover:opacity-50",
            LEVEL_COLOR[level],
          )}
        >
          <Icon
            aria-hidden="true"
            className="size-4"
          />
        </button>
      </div>
    );
  };

  const sortedFolders = byName(level.data?.folders ?? [], (item: FolderItem) => item.name);
  const sortedFiles = byName(level.data?.files ?? [], (item: OrgFileResponse) => item.filename);
  const isLoading = level.isPending || acl.isPending;
  const hasFailed = level.isError || acl.isError;

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 p-4">
      <h1 className="text-lg font-semibold tracking-tight">
        {t("access.heading", { name: principalName })}
      </h1>

      {pathIds.map((ancestorId, index) => (
        <AncestorNameProbe
          key={ancestorId}
          parentId={index === 0 ? null : pathIds[index - 1]}
          folderId={ancestorId}
          onResolved={(name) =>
            setAncestorNames((current) =>
              // Bail out when nothing changed: `onResolved` is a fresh closure
              // every render, so without this guard the effect below would
              // re-fire on every state update it causes, looping forever.
              current[ancestorId] === name ? current : { ...current, [ancestorId]: name },
            )
          }
        />
      ))}

      <Breadcrumb
        pathIds={pathIds}
        onNavigate={goToLevel}
        onMissing={goToLevel}
      />

      <p
        role="note"
        className="text-muted-foreground text-xs"
      >
        {t("access.cascadeWarning")}
      </p>

      <div className="text-muted-foreground flex flex-wrap items-center gap-3 text-xs">
        <span className="font-medium">{t("access.legendTitle")}</span>
        {(["none", "read", "write"] satisfies AccessLevel[]).map((level) => {
          const Icon = LEVEL_ICON[level];
          return (
            <span
              key={level}
              className={cn("flex items-center gap-1", LEVEL_COLOR[level])}
            >
              <Icon
                aria-hidden="true"
                className="size-4"
              />
              {t(`access.level.${level}`)}
            </span>
          );
        })}
      </div>

      {isLoading && <Skeleton className="h-10 w-full" />}
      {!isLoading && hasFailed && (
        <p className="text-destructive text-sm">{t("access.loadError")}</p>
      )}
      {!isLoading && !hasFailed && (
        <ItemList
          folders={sortedFolders}
          files={sortedFiles}
          onOpen={open}
          renderFolderActions={(folder) => renderToggle("folder", folder.id, folder.name)}
          renderFileActions={(file) => renderToggle("document", file.id, file.filename)}
        />
      )}
    </div>
  );
};
