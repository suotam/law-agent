import type { ReactNode } from "react";
import { FileText } from "lucide-react";
import { formatBytes } from "../format";
import type { OrgFileResponse } from "../types";

type FileRowProps = {
  file: OrgFileResponse;
  actions?: ReactNode;
};

export const FileRow = ({ file, actions }: FileRowProps) => (
  <li className="border-border flex items-center gap-2 border-b px-2 py-2 text-sm last:border-b-0">
    <FileText
      aria-hidden="true"
      className="text-muted-foreground size-4 shrink-0"
    />
    <span className="min-w-0 flex-1 truncate">{file.filename}</span>
    <span className="text-muted-foreground shrink-0 text-xs">{formatBytes(file.byte_size)}</span>
    {actions}
  </li>
);
