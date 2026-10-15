import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { FolderItem, OrgFileResponse } from "../types";
import { FileRow } from "./FileRow";
import { FolderRow } from "./FolderRow";

type ItemListProps = {
  folders: FolderItem[];
  files: OrgFileResponse[];
  onOpen: (id: string) => void;
  renderFolderActions?: (folder: FolderItem) => ReactNode;
  renderFileActions?: (file: OrgFileResponse) => ReactNode;
  /** Rows for files still uploading; they belong between the finished ones. */
  pendingRows?: ReactNode;
};

export const ItemList = ({
  folders,
  files,
  onOpen,
  renderFolderActions,
  renderFileActions,
  pendingRows,
}: ItemListProps) => {
  const { t } = useTranslation();
  const isEmpty = folders.length === 0 && files.length === 0 && pendingRows === undefined;

  if (isEmpty)
    return <p className="text-muted-foreground py-8 text-center text-sm">{t("orgFiles.empty")}</p>;

  return (
    <ul className="border-border divide-border rounded-md border">
      {folders.map((folder) => (
        <FolderRow
          key={folder.id}
          folder={folder}
          onOpen={onOpen}
          actions={renderFolderActions?.(folder)}
        />
      ))}
      {files.map((file) => (
        <FileRow
          key={file.id}
          file={file}
          actions={renderFileActions?.(file)}
        />
      ))}
      {pendingRows}
    </ul>
  );
};
