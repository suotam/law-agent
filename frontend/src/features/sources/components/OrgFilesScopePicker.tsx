import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { useFolderLevel } from "@/features/org-files/api/get-folders";
import type { FolderItem } from "@/features/org-files/types";
import { useOrgFilesScopeStore } from "../org-files-scope-store";

type FolderNodeProps = {
  id: string;
  name: string;
  /** Every ancestor folder id from the root down to (not including) this
   * node -- needed so that unchecking a deep node can also clear an
   * ancestor's "whole subtree" checked state, turning it indeterminate
   * instead of leaving it wrongly checked. */
  ancestorIds?: string[];
};

/** One folder node: fetches its own children once expanded, so the tree
 * never pays for a subtree the user never opens. Recursive by construction --
 * a grandchild renders as another `FolderNode` inside its parent's. */
const FolderNode = ({ id, name, ancestorIds = [] }: FolderNodeProps) => {
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);
  const contents = useFolderLevel(id, isOpen);
  const folderIds = useOrgFilesScopeStore((state) => state.folderIds);
  const setFolderChecked = useOrgFilesScopeStore((state) => state.setFolderChecked);
  const isLocked = useOrgFilesScopeStore((state) => state.isLocked);

  const children = contents.data?.folders ?? [];
  const isChecked = folderIds.includes(id);
  const isAncestorChecked = ancestorIds.some((ancestorId) => folderIds.includes(ancestorId));
  // A checked ancestor already covers this node's whole subtree. Nodes that
  // were loaded (and so explicitly cascaded into `folderIds`) at check time
  // stay independently toggleable -- narrowing the selection back down is
  // still allowed. A node discovered later, by expanding after the fact,
  // was never added to the store: it is only checked by inheritance, so
  // unchecking it in the UI would be a no-op lie, and it's locked instead.
  const isLockedByAncestor = isAncestorChecked && !isChecked;
  // Indeterminate only makes sense once children are loaded -- an unopened
  // folder cannot know whether "some but not all" applies.
  const checkedChildCount = children.filter((child) => folderIds.includes(child.id)).length;
  const isIndeterminate =
    !isChecked &&
    !isAncestorChecked &&
    isOpen &&
    checkedChildCount > 0 &&
    checkedChildCount < children.length;

  const onToggle = () => {
    if (isLockedByAncestor) return; // the input is disabled too; guards a bypassed change event
    const next = !isChecked;
    setFolderChecked(id, next);
    // Checking a folder checks everything already loaded under it, matching
    // what selecting it will actually search; a user may then uncheck
    // individual children without that ever widening the selection back.
    for (const child of children) setFolderChecked(child.id, next);
    if (!next) {
      // Unchecking this folder breaks any ancestor's "whole subtree" claim
      // too -- an ancestor still marked fully checked would be a lie once
      // one of its descendants is not.
      for (const ancestorId of ancestorIds) setFolderChecked(ancestorId, false);
    }
  };

  return (
    <li>
      <div className="flex items-center gap-2">
        <input
          type="checkbox"
          aria-label={t("sources.orgFilesFolderCheckboxLabel", { name })}
          checked={isChecked || isAncestorChecked}
          disabled={isLocked || isLockedByAncestor}
          ref={(node) => {
            if (node) node.indeterminate = isIndeterminate;
          }}
          onChange={onToggle}
        />
        <button
          type="button"
          aria-expanded={isOpen}
          onClick={() => setIsOpen((open) => !open)}
          className="flex items-center gap-1 text-left"
        >
          <ChevronRight
            aria-hidden="true"
            className={cn(
              "text-muted-foreground size-4 shrink-0 transition-transform",
              isOpen && "rotate-90",
            )}
          />
          {name}
        </button>
      </div>
      {isOpen && (
        <ul className="ml-5">
          {contents.isPending && <Skeleton className="h-4 w-32" />}
          {children.map((child: FolderItem) => (
            <FolderNode
              key={child.id}
              id={child.id}
              name={child.name}
              ancestorIds={[...ancestorIds, id]}
            />
          ))}
          {(contents.data?.files ?? []).map((file) => (
            <FileLeaf
              key={file.id}
              id={file.id}
              name={file.filename}
              // A checked folder covers every document under it without
              // needing each document's id in the store -- the leaf just
              // reflects that coverage, checked and locked.
              parentChecked={isChecked || isAncestorChecked}
            />
          ))}
        </ul>
      )}
    </li>
  );
};

type FileLeafProps = {
  id: string;
  name: string;
  /** True once the containing folder is (or is under) a checked selection --
   * the document is already covered by that folder search, so its checkbox
   * is shown checked and locked rather than independently toggleable. */
  parentChecked: boolean;
};

const FileLeaf = ({ id, name, parentChecked }: FileLeafProps) => {
  const { t } = useTranslation();
  const documentIds = useOrgFilesScopeStore((state) => state.documentIds);
  const toggleDocument = useOrgFilesScopeStore((state) => state.toggleDocument);
  const isLocked = useOrgFilesScopeStore((state) => state.isLocked);

  return (
    <li className="flex items-center gap-2">
      <input
        type="checkbox"
        aria-label={t("sources.orgFilesDocumentCheckboxLabel", { name })}
        checked={documentIds.includes(id) || parentChecked}
        disabled={isLocked || parentChecked}
        onChange={() => toggleDocument(id)}
      />
      <span>{name}</span>
    </li>
  );
};

export const OrgFilesScopePicker = () => {
  const { t } = useTranslation();
  // Roots are the top-level entry: `useFolderLevel(null)` returns them under
  // `.folders`, the same shape a folder's own contents come back in.
  const roots = useFolderLevel(null);
  const rootFolders = roots.data?.folders ?? [];

  const hasNothing = !roots.isPending && rootFolders.length === 0;

  return (
    <div className="flex w-full max-w-md flex-col gap-3 rounded-lg border p-3">
      <p className="text-sm font-medium">{t("sources.orgFilesPickerTitle")}</p>
      {roots.isPending && <Skeleton className="h-4 w-40" />}
      {roots.isError && (
        <p className="text-destructive text-sm">{t("sources.orgFilesPickerLoadError")}</p>
      )}
      {hasNothing && (
        <p className="text-muted-foreground text-sm">{t("sources.orgFilesPickerEmpty")}</p>
      )}
      {!roots.isPending && !roots.isError && rootFolders.length > 0 && (
        <ul>
          {rootFolders.map((root: FolderItem) => (
            <FolderNode
              key={root.id}
              id={root.id}
              name={root.name}
            />
          ))}
        </ul>
      )}
    </div>
  );
};
