import { LoaderCircle, RotateCw, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { MAX_FILE_MB } from "../file-rules";
import { AttachmentBase } from "./AttachmentBase";
import type { AttachmentUpload } from "../types";

type AttachmentChipsProps = {
  uploads: AttachmentUpload[];
  onDismiss: (localId: string) => void;
  onRetry: (localId: string) => void;
};

export const AttachmentChips = ({ uploads, onDismiss, onRetry }: AttachmentChipsProps) => {
  const { t } = useTranslation();

  if (uploads.length === 0) return null;

  return (
    <ul className="flex flex-wrap gap-2">
      {uploads.map((upload) => (
        <AttachmentBase
          key={upload.localId}
          filename={upload.filename}
          className={upload.status === "error" ? "bg-destructive/10 text-destructive" : undefined}
          icon={
            upload.status === "uploading" ? (
              <LoaderCircle
                aria-hidden="true"
                className="size-3.5 shrink-0 animate-spin"
              />
            ) : undefined
          }
        >
          {upload.status === "error" && (
            <>
              {/* A refused file names its reason; for a failed upload the 500 body carries
                  no detail, so the message cannot be more specific than "it failed". */}
              <span className="text-xs">
                {upload.rejectionKey
                  ? t(upload.rejectionKey, { limit: MAX_FILE_MB })
                  : t("attachments.failed")}
              </span>
              {/* Retrying a refused file would fail on the same rule, so it is not offered. */}
              {upload.rejectionKey === undefined && (
                <Button
                  variant="ghost"
                  size="icon-xs"
                  aria-label={t("attachments.retryLabel")}
                  onClick={() => onRetry(upload.localId)}
                >
                  <RotateCw aria-hidden="true" />
                </Button>
              )}
            </>
          )}

          {/* Only unsent chips are shown at all: an attachment used by a sent message
              cannot be deleted, so the chips are cleared once the turn goes out. */}
          <Button
            variant="ghost"
            size="icon-xs"
            aria-label={
              upload.status === "uploading"
                ? t("attachments.cancelLabel")
                : t("attachments.removeLabel")
            }
            onClick={() => onDismiss(upload.localId)}
          >
            <X aria-hidden="true" />
          </Button>
        </AttachmentBase>
      ))}
    </ul>
  );
};
