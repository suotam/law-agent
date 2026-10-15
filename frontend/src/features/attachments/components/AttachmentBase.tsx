import type { ReactNode } from "react";
import { FileText } from "lucide-react";
import { cn } from "@/lib/utils";

type AttachmentBaseProps = {
  filename: string;
  /** Replaces the file icon; the composer swaps in a spinner while the upload runs. */
  icon?: ReactNode;
  className?: string;
  /** Trailing slot for the affordances only an unsent chip has. */
  children?: ReactNode;
};

/** The look of a file chip, shared by the composer's editable chips and a sent message's. */
export const AttachmentBase = ({ filename, icon, className, children }: AttachmentBaseProps) => (
  <li className={cn("bg-muted flex items-center gap-1.5 rounded-lg px-2 py-1 text-sm", className)}>
    {icon ?? (
      <FileText
        aria-hidden="true"
        className="size-3.5 shrink-0"
      />
    )}
    {/* Long names are truncated, so the full one has to stay reachable on hover. */}
    <span
      className="max-w-40 truncate"
      title={filename}
    >
      {filename}
    </span>
    {children}
  </li>
);
