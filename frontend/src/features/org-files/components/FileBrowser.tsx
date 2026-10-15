import { useMemo, useState } from "react";
import type { ParseKeys } from "i18next";
import { Download, FolderPen, FolderPlus, Share2, Trash2, Upload } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useHasCapability } from "@/features/auth";
import { FILE_INPUT_ACCEPT } from "@/features/attachments";
import { SharePanel } from "@/features/groups";
import { translateError } from "@/lib/errors";
import { useDeleteFolder } from "../api/delete-folder";
import { useDeleteDocument } from "../api/delete-document";
import { useDownloadDocument } from "../api/download-document";
import { useFolderLevel } from "../api/get-folders";
import { useUploadDocuments } from "../api/upload-document";
import { useFolderPath } from "../path";
import type { FolderItem, OrgFileResponse } from "../types";
import { Breadcrumb } from "./Breadcrumb";
import { DeleteDialog } from "./DeleteDialog";
import { FolderDialog } from "./FolderDialog";
import { ItemList } from "./ItemList";
import { PendingFileRow } from "./PendingFileRow";
import { RowActions } from "./RowActions";
import { UploadDropzone } from "./UploadDropzone";

const byName = <T,>(items: T[], nameOf: (item: T) => string): T[] =>
  [...items].sort((a, b) => nameOf(a).localeCompare(nameOf(b), "cs"));

const canWrite = (node: { effective_permission: string | null; is_structure_manager: boolean }) =>
  node.effective_permission === "write" || node.is_structure_manager;

type DeleteTarget =
  { kind: "folder"; folder: FolderItem } | { kind: "file"; file: OrgFileResponse };

export const FileBrowser = () => {
  const { t } = useTranslation();
  const hasStructureCapability = useHasCapability("manage_org_files_structure");
  const hasManageGroups = useHasCapability("manage_groups");
  const hasManageUsers = useHasCapability("manage_users");
  const { pathIds, folderId, open, goToLevel } = useFolderPath();
  const level = useFolderLevel(folderId);
  /*
   * A node's own permission is only ever reported on its parent's listing, so
   * the open folder's permission comes from the level above it -- a query the
   * breadcrumb already holds, which also makes a deep link work on reload.
   */
  const parentLevel = useFolderLevel(pathIds.at(-2) ?? null);
  const currentFolder = parentLevel.data?.folders.find((folder) => folder.id === folderId) ?? null;

  const [dialogState, setDialogState] = useState<{ open: boolean; folder: FolderItem | null }>({
    open: false,
    folder: null,
  });
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget | null>(null);
  const [deleteErrorKey, setDeleteErrorKey] = useState<ParseKeys | null>(null);
  const [shareTarget, setShareTarget] = useState<{
    resourceType: "folder" | "document";
    resourceId: string;
    resourceName: string;
  } | null>(null);
  const deleteFolderMutation = useDeleteFolder(folderId);
  const deleteFileMutation = useDeleteDocument(folderId);
  const { uploads, addFiles, retry, dismiss } = useUploadDocuments();
  const { download, downloadingId, hasFailed: hasDownloadFailed } = useDownloadDocument();
  const pendingHere = uploads.filter((upload) => upload.folderId === folderId);

  const sortedFolders = useMemo(
    () => byName(level.data?.folders ?? [], (item) => item.name),
    [level.data],
  );
  const sortedFiles = useMemo(
    () => byName(level.data?.files ?? [], (item) => item.filename),
    [level.data],
  );

  /*
   * A user-level flag, identical on every row the server sends, so any loaded
   * node answers it; only where no node is loaded at all does the caller's
   * own capability stand in (an empty tree, where the create-folder button
   * is the way out).
   */
  const isStructureManager =
    currentFolder?.is_structure_manager ??
    [...sortedFolders, ...sortedFiles].some((node) => node.is_structure_manager);
  const canManageStructure = isStructureManager || hasStructureCapability;
  // Sharing edits ACL entries, gated per principal type (see acl.py):
  // manage_groups for a group grant, manage_users for a user grant. Either
  // capability is enough to open the panel; SharePanel narrows further.
  const canShare = hasManageGroups || hasManageUsers;
  const canUpload = currentFolder !== null && canWrite(currentFolder);

  const handleFiles = (files: File[]) => {
    if (folderId === null || !canUpload || files.length === 0) return;
    addFiles(folderId, files);
  };

  const closeDelete = () => {
    setDeleteTarget(null);
    setDeleteErrorKey(null);
  };

  const confirmDelete = async () => {
    if (deleteTarget === null) return;
    setDeleteErrorKey(null);

    try {
      if (deleteTarget.kind === "folder")
        await deleteFolderMutation.mutateAsync(deleteTarget.folder.id);
      else await deleteFileMutation.mutateAsync(deleteTarget.file.id);

      closeDelete();
    } catch (error) {
      // A 409 on a folder means only one thing here: it still holds files or subfolders.
      setDeleteErrorKey(
        deleteTarget.kind === "folder" && translateError(error).status === 409
          ? "orgFiles.deleteFolderNotEmpty"
          : "orgFiles.deleteFailed",
      );
    }
  };

  const isLoading = level.isPending;
  const hasFailed = level.isError;

  const renderFolderActions = (folder: FolderItem) => {
    const items = [
      ...(canManageStructure
        ? [
            {
              key: "rename",
              label: t("orgFiles.renameLabel"),
              icon: <FolderPen aria-hidden="true" />,
              onSelect: () => setDialogState({ open: true, folder }),
            },
          ]
        : []),
      ...(canShare
        ? [
            {
              key: "share",
              label: t("orgFiles.shareLabel"),
              icon: <Share2 aria-hidden="true" />,
              onSelect: () =>
                setShareTarget({
                  resourceType: "folder" as const,
                  resourceId: folder.id,
                  resourceName: folder.name,
                }),
            },
          ]
        : []),
      // Structure operations stay capability-gated: `write` on a folder covers
      // its documents, never the shape of the tree.
      ...(canManageStructure
        ? [
            {
              key: "delete",
              label: t("orgFiles.deleteFolderLabel"),
              icon: <Trash2 aria-hidden="true" />,
              onSelect: () => setDeleteTarget({ kind: "folder", folder }),
            },
          ]
        : []),
    ];

    return items.length === 0 ? null : <RowActions items={items} />;
  };

  const renderFileActions = (file: OrgFileResponse) => {
    const items = [
      // A visible row is already readable, so downloading needs no further check.
      {
        key: "download",
        label: t("orgFiles.downloadLabel"),
        icon: <Download aria-hidden="true" />,
        isBusy: downloadingId === file.id,
        onSelect: () => void download(file),
      },
      ...(canShare
        ? [
            {
              key: "share",
              label: t("orgFiles.shareLabel"),
              icon: <Share2 aria-hidden="true" />,
              onSelect: () =>
                setShareTarget({
                  resourceType: "document" as const,
                  resourceId: file.id,
                  resourceName: file.filename,
                }),
            },
          ]
        : []),
      ...(canWrite(file)
        ? [
            {
              key: "delete",
              label: t("orgFiles.deleteFileLabel"),
              icon: <Trash2 aria-hidden="true" />,
              onSelect: () => setDeleteTarget({ kind: "file", file }),
            },
          ]
        : []),
    ];

    return <RowActions items={items} />;
  };

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 p-4">
      <h1 className="text-lg font-semibold tracking-tight">{t("orgFiles.heading")}</h1>

      <div className="flex items-center justify-between gap-2">
        <Breadcrumb
          pathIds={pathIds}
          onNavigate={goToLevel}
          onMissing={goToLevel}
        />

        <div className="flex shrink-0 items-center gap-2">
          {canManageStructure && (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setDialogState({ open: true, folder: null })}
            >
              <FolderPlus aria-hidden="true" />
              {t("orgFiles.newFolder")}
            </Button>
          )}

          {folderId === null ? (
            <Button
              variant="secondary"
              size="sm"
              disabled
              title={t("orgFiles.uploadNeedsFolder")}
            >
              <Upload aria-hidden="true" />
              {t("orgFiles.uploadFile")}
            </Button>
          ) : (
            canUpload && (
              <Button
                variant="secondary"
                size="sm"
                render={<label />}
                className="cursor-pointer"
              >
                <Upload aria-hidden="true" />
                {t("orgFiles.uploadFile")}
                <input
                  type="file"
                  multiple
                  aria-label={t("orgFiles.uploadFile")}
                  accept={FILE_INPUT_ACCEPT}
                  className="sr-only"
                  onChange={(event) => {
                    handleFiles(Array.from(event.target.files ?? []));
                    // Re-picking the same file must fire change again.
                    event.target.value = "";
                  }}
                />
              </Button>
            )
          )}
        </div>
      </div>

      {isLoading && (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      )}

      {!isLoading && hasFailed && (
        <p className="text-destructive text-sm">{t("orgFiles.loadError")}</p>
      )}

      {!isLoading && !hasFailed && (
        <UploadDropzone
          isEnabled={canUpload}
          onFiles={handleFiles}
        >
          <ItemList
            folders={sortedFolders}
            files={sortedFiles}
            onOpen={open}
            renderFolderActions={renderFolderActions}
            renderFileActions={renderFileActions}
            pendingRows={
              pendingHere.length === 0
                ? undefined
                : pendingHere.map((upload) => (
                    <PendingFileRow
                      key={upload.localId}
                      upload={upload}
                      onRetry={() => retry(upload.localId)}
                      onDismiss={() => dismiss(upload.localId)}
                    />
                  ))
            }
          />
        </UploadDropzone>
      )}

      {hasDownloadFailed && (
        <p className="text-destructive text-sm">{t("orgFiles.downloadFailed")}</p>
      )}

      <FolderDialog
        open={dialogState.open}
        onOpenChange={(isOpen) => setDialogState((current) => ({ ...current, open: isOpen }))}
        folder={dialogState.folder}
        parentId={folderId}
      />

      <DeleteDialog
        open={deleteTarget !== null}
        onOpenChange={(isOpen) => !isOpen && closeDelete()}
        title={t(
          deleteTarget?.kind === "file" ? "orgFiles.deleteFileTitle" : "orgFiles.deleteFolderTitle",
        )}
        description={t(
          deleteTarget?.kind === "file"
            ? "orgFiles.deleteFileDescription"
            : "orgFiles.deleteFolderDescription",
        )}
        errorMessage={deleteErrorKey === null ? null : t(deleteErrorKey)}
        isPending={deleteFolderMutation.isPending || deleteFileMutation.isPending}
        onConfirm={() => void confirmDelete()}
      />

      {shareTarget !== null && (
        <SharePanel
          open
          onOpenChange={(isOpen) => !isOpen && setShareTarget(null)}
          resourceType={shareTarget.resourceType}
          resourceId={shareTarget.resourceId}
          resourceName={shareTarget.resourceName}
        />
      )}
    </div>
  );
};
