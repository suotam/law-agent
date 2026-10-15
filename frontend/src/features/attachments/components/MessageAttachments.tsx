import { useTranslation } from "react-i18next";
import { AttachmentBase } from "./AttachmentBase";
import type { MessageAttachment } from "../types";

type MessageAttachmentsProps = {
  items: MessageAttachment[];
};

/*
 * The files a sent question carried. Read-only by necessity: an attachment a message has used
 * cannot be deleted, and the API offers nothing to open or download it with.
 */
export const MessageAttachments = ({ items }: MessageAttachmentsProps) => {
  const { t } = useTranslation();

  if (items.length === 0) return null;

  return (
    <ul
      aria-label={t("attachments.sentLabel")}
      className="flex flex-wrap justify-end gap-1.5"
    >
      {items.map((item) => (
        <AttachmentBase
          key={item.id}
          filename={item.filename}
        />
      ))}
    </ul>
  );
};
