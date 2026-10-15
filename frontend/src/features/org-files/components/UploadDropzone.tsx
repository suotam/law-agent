import { useState, type DragEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";

type UploadDropzoneProps = {
  /** False at the root, where the API has no endpoint to upload into. */
  isEnabled: boolean;
  onFiles: (files: File[]) => void;
  children: ReactNode;
};

export const UploadDropzone = ({ isEnabled, onFiles, children }: UploadDropzoneProps) => {
  const { t } = useTranslation();
  const [isDragging, setIsDragging] = useState(false);

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragging(false);
    if (!isEnabled) return;

    onFiles(Array.from(event.dataTransfer.files));
  };

  return (
    <div
      onDragOver={(event) => {
        event.preventDefault();
        if (isEnabled) setIsDragging(true);
      }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={handleDrop}
      className={cn("rounded-md", isDragging && "ring-primary ring-2")}
    >
      {isDragging && (
        <p className="text-muted-foreground py-2 text-center text-sm">{t("orgFiles.dropHint")}</p>
      )}
      {children}
    </div>
  );
};
