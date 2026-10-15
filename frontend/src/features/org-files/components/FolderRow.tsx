import type { ReactNode } from "react";
import { Folder } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { FolderItem } from "../types";

type FolderRowProps = {
  folder: FolderItem;
  onOpen: (id: string) => void;
  actions?: ReactNode;
};

export const FolderRow = ({ folder, onOpen, actions }: FolderRowProps) => {
  const { t } = useTranslation();

  return (
    <li className="border-border flex items-center gap-2 border-b last:border-b-0">
      <button
        type="button"
        aria-label={t("orgFiles.openFolder", { name: folder.name })}
        onClick={() => onOpen(folder.id)}
        className="hover:bg-accent flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-2 text-left text-sm"
      >
        <Folder
          aria-hidden="true"
          className="text-muted-foreground size-4 shrink-0"
        />
        <span className="truncate">{folder.name}</span>
      </button>
      {actions}
    </li>
  );
};
