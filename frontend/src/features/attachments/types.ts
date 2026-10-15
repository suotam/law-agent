import type { ParseKeys } from "i18next";

/**
 * A file as it is remembered against the message that used it. These four fields are exactly
 * what `GET /history` puts in the message's `data-attachments` part, so the same object serves
 * the live turn and the reloaded one.
 */
export type MessageAttachment = {
  id: string;
  filename: string;
  mime: string;
  byte_size: number;
};

export type AttachmentResponse = MessageAttachment & {
  /*
   * Only "indexed" ever reaches the frontend: the service re-raises after marking a
   * document failed, so a failure is a 500 and never a status value. Kept as a plain
   * string because nothing branches on it.
   */
  status: string;
};

export type UploadStatus = "uploading" | "ready" | "error";

export type AttachmentUpload = {
  /** Client-side key; the server-side file only exists once the upload resolves. */
  localId: string;
  filename: string;
  status: UploadStatus;
  attachment?: MessageAttachment;
  /*
   * Set only when the file was refused before any request went out. Such a chip names its own
   * reason and offers no retry — re-sending the same file would fail the same way.
   */
  rejectionKey?: ParseKeys;
};
