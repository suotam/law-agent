import { apiClient } from "@/lib/api-client";
import type { AttachmentResponse } from "../types";

export const uploadAttachment = async (
  file: File,
  signal: AbortSignal,
  /*
   * Claims the file for the thread straight away, so an existing conversation processes it
   * in one go. A new chat has no thread yet — the first message claims it instead.
   */
  conversationId: string | null,
): Promise<AttachmentResponse> => {
  const formData = new FormData();
  formData.append("file", file);
  if (conversationId !== null) formData.append("conversation_id", conversationId);

  // The request blocks until the file is parsed and indexed — tens of seconds for a
  // scanned PDF — so no timeout is set and the chip's state follows this request.
  const { data } = await apiClient.post<AttachmentResponse>("/attachments", formData, {
    signal,
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 0,
  });

  return data;
};

export const deleteAttachment = async (attachmentId: string): Promise<void> => {
  await apiClient.delete(`/attachments/${attachmentId}`);
};
