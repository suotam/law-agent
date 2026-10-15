import { useCallback, useRef, useState } from "react";
import { deleteAttachment, uploadAttachment } from "../api/attachments-api";
import { rejectionKeyFor } from "../file-rules";
import type { AttachmentUpload, MessageAttachment } from "../types";

type PendingUpload = {
  controller: AbortController;
  promise: Promise<void>;
};

/**
 * @param getConversationId Read per request, not once: a new chat gains its thread while
 *   files are already uploading, and every upload after that point can be claimed at once.
 */
export const useAttachmentUploads = (getConversationId: () => string | null) => {
  const [uploads, setUploads] = useState<AttachmentUpload[]>([]);
  const pendingRef = useRef(new Map<string, PendingUpload>());
  /** Kept so retry can re-upload the same File after pendingRef has been cleared. */
  const filesRef = useRef(new Map<string, File>());
  /** Mirrors the resolved files: the wait below runs before the last state patch flushes. */
  const readyAttachmentsRef = useRef<MessageAttachment[]>([]);

  const patch = useCallback((localId: string, changes: Partial<AttachmentUpload>) => {
    setUploads((current) =>
      current.map((upload) => (upload.localId === localId ? { ...upload, ...changes } : upload)),
    );
  }, []);

  const startUpload = useCallback(
    (localId: string, file: File) => {
      const controller = new AbortController();

      const promise = uploadAttachment(file, controller.signal, getConversationId())
        .then(({ id, filename, mime, byte_size }) => {
          const attachment = { id, filename, mime, byte_size };
          readyAttachmentsRef.current = [...readyAttachmentsRef.current, attachment];
          patch(localId, { status: "ready", attachment });
        })
        .catch(() => {
          // A failed ingest arrives as a 500 with no usable detail, and an abort lands
          // here too — but an aborted upload has already been removed from the list.
          patch(localId, { status: "error" });
        })
        .finally(() => {
          pendingRef.current.delete(localId);
        });

      pendingRef.current.set(localId, { controller, promise });
    },
    [getConversationId, patch],
  );

  const addFiles = useCallback(
    (files: File[]) => {
      // One request per file, even when several are dropped at once.
      files.forEach((file) => {
        const localId = crypto.randomUUID();
        const rejectionKey = rejectionKeyFor(file);

        if (rejectionKey !== null) {
          // Refused files still get a chip: a file that silently vanishes reads as a bug.
          setUploads((current) => [
            ...current,
            { localId, filename: file.name, status: "error", rejectionKey },
          ]);
          return;
        }

        filesRef.current.set(localId, file);
        setUploads((current) => [
          ...current,
          { localId, filename: file.name, status: "uploading" },
        ]);
        startUpload(localId, file);
      });
    },
    [startUpload],
  );

  /** Forgets an entry entirely: chip, queued file, in-flight request and retained File. */
  const forget = useCallback((localId: string, attachmentId?: string) => {
    pendingRef.current.get(localId)?.controller.abort();
    pendingRef.current.delete(localId);
    filesRef.current.delete(localId);
    readyAttachmentsRef.current = readyAttachmentsRef.current.filter(
      ({ id }) => id !== attachmentId,
    );
    setUploads((current) => current.filter((upload) => upload.localId !== localId));
  }, []);

  const cancel = useCallback(
    (localId: string) => {
      const upload = uploads.find((entry) => entry.localId === localId);
      forget(localId, upload?.attachment?.id);
    },
    [forget, uploads],
  );

  const retry = useCallback(
    (localId: string) => {
      const file = filesRef.current.get(localId);
      if (file === undefined) return;

      patch(localId, { status: "uploading" });
      startUpload(localId, file);
    },
    [patch, startUpload],
  );

  const remove = useCallback(
    async (localId: string) => {
      const upload = uploads.find((entry) => entry.localId === localId);
      forget(localId, upload?.attachment?.id);

      if (upload?.attachment) {
        // A 404 here means the attachment was already used by a sent message; nothing to do.
        await deleteAttachment(upload.attachment.id).catch(() => undefined);
      }
    },
    [forget, uploads],
  );

  const waitForReadyAttachments = useCallback(async (): Promise<MessageAttachment[]> => {
    await Promise.all([...pendingRef.current.values()].map((pending) => pending.promise));

    // Read from the ref rather than state: the last patch may not have flushed yet.
    return readyAttachmentsRef.current;
  }, []);

  const clear = useCallback(() => {
    /*
     * Aborted, not merely forgotten: an upload left running would resolve into the ready list
     * after the fact and attach itself to whichever turn the user sends next.
     */
    pendingRef.current.forEach((pending) => pending.controller.abort());
    pendingRef.current.clear();
    filesRef.current.clear();
    readyAttachmentsRef.current = [];
    setUploads([]);
  }, []);

  return {
    uploads,
    hasPendingUploads: uploads.some((upload) => upload.status === "uploading"),
    addFiles,
    cancel,
    retry,
    remove,
    waitForReadyAttachments,
    clear,
  };
};
