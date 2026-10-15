export { deleteAttachment, uploadAttachment } from "./api/attachments-api";
export { AttachmentBase } from "./components/AttachmentBase";
export { AttachmentChips } from "./components/AttachmentChips";
export { MessageAttachments } from "./components/MessageAttachments";
export { FILE_INPUT_ACCEPT, MAX_FILE_MB, rejectionKeyFor } from "./file-rules";
export { useAttachmentUploads } from "./hooks/useAttachmentUploads";
export type {
  AttachmentResponse,
  AttachmentUpload,
  MessageAttachment,
  UploadStatus,
} from "./types";
