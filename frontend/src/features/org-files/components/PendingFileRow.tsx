import { LoaderCircle, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { MAX_FILE_MB } from "@/features/attachments";
import type { OrgFileUpload } from "../api/upload-document";

type PendingFileRowProps = {
  upload: OrgFileUpload;
  onRetry: () => void;
  onDismiss: () => void;
};

export const PendingFileRow = ({ upload, onRetry, onDismiss }: PendingFileRowProps) => {
  const { t } = useTranslation();

  return (
    <li className="border-border flex items-center gap-2 border-b px-2 py-2 text-sm last:border-b-0">
      {upload.status === "uploading" ? (
        <LoaderCircle
          aria-hidden="true"
          className="text-muted-foreground size-4 shrink-0 animate-spin"
        />
      ) : (
        <X
          aria-hidden="true"
          className="text-destructive size-4 shrink-0"
        />
      )}

      <span className="min-w-0 flex-1 truncate">{upload.filename}</span>

      {upload.status === "uploading" ? (
        <span className="text-muted-foreground shrink-0 text-xs">{t("orgFiles.uploading")}</span>
      ) : (
        <span className="text-destructive shrink-0 text-xs">
          {upload.errorKey && t(upload.errorKey, { limit: MAX_FILE_MB })}
        </span>
      )}

      {upload.status === "error" && upload.canRetry && (
        <Button
          variant="ghost"
          size="sm"
          onClick={onRetry}
        >
          {t("common.retry")}
        </Button>
      )}

      {upload.status === "error" && (
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={t("orgFiles.dismissLabel")}
          onClick={onDismiss}
        >
          <X aria-hidden="true" />
        </Button>
      )}
    </li>
  );
};
