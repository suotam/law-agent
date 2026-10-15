import { useCallback, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { ParseKeys } from "i18next";
import { rejectionKeyFor } from "@/features/attachments";
import { apiClient } from "@/lib/api-client";
import { translateError } from "@/lib/errors";
import type { OrgFileResponse } from "../types";
import { orgFileQueryKeys } from "./query-keys";

/** Member upload into a folder the caller has write access to. A structure
 * manager passes the server's write check trivially, so this one endpoint
 * serves both and the browser needs no second upload path. */
export const uploadDocument = async (folderId: string, file: File): Promise<OrgFileResponse> => {
  const formData = new FormData();
  formData.append("file", file);

  // The request blocks until the document is parsed and indexed — tens of seconds for a
  // scanned PDF — so it runs without a timeout, as chat attachments do.
  const { data } = await apiClient.post<OrgFileResponse>(
    `/me/org-files/folders/${folderId}/documents`,
    formData,
    { headers: { "Content-Type": "multipart/form-data" }, timeout: 0 },
  );

  return data;
};

export type OrgFileUpload = {
  localId: string;
  /** The folder this upload belongs to: switching folders must not show it elsewhere. */
  folderId: string;
  filename: string;
  status: "uploading" | "error";
  errorKey?: ParseKeys;
  canRetry: boolean;
};

type UploadDocuments = {
  uploads: OrgFileUpload[];
  addFiles: (folderId: string, files: File[]) => void;
  retry: (localId: string) => void;
  dismiss: (localId: string) => void;
};

export const useUploadDocuments = (): UploadDocuments => {
  const queryClient = useQueryClient();
  const [uploads, setUploads] = useState<OrgFileUpload[]>([]);
  /** Kept so a retry can re-send the same File after the first attempt failed. */
  const filesRef = useRef(new Map<string, File>());

  const start = useCallback(
    (localId: string, folderId: string, file: File) => {
      setUploads((current) =>
        current.map((upload) =>
          upload.localId === localId
            ? { ...upload, status: "uploading", errorKey: undefined, canRetry: false }
            : upload,
        ),
      );

      void uploadDocument(folderId, file)
        .then(async () => {
          filesRef.current.delete(localId);
          // The finished file arrives from the listing itself; the pending row has no more to say.
          setUploads((current) => current.filter((upload) => upload.localId !== localId));
          await queryClient.invalidateQueries({ queryKey: orgFileQueryKeys.level(folderId) });
        })
        .catch((error: unknown) => {
          // 409 is the same blob already in this folder — re-sending it would fail identically.
          const isDuplicate = translateError(error).status === 409;

          setUploads((current) =>
            current.map((upload) =>
              upload.localId === localId
                ? {
                    ...upload,
                    status: "error",
                    errorKey: isDuplicate ? "orgFiles.uploadDuplicate" : "orgFiles.uploadFailed",
                    canRetry: !isDuplicate,
                  }
                : upload,
            ),
          );
        });
    },
    [queryClient],
  );

  const addFiles = useCallback(
    (folderId: string, files: File[]) => {
      // One request per file, even when several are dropped at once.
      files.forEach((file) => {
        const localId = crypto.randomUUID();
        const rejectionKey = rejectionKeyFor(file);

        if (rejectionKey !== null) {
          setUploads((current) => [
            ...current,
            {
              localId,
              folderId,
              filename: file.name,
              status: "error",
              errorKey: rejectionKey,
              canRetry: false,
            },
          ]);
          return;
        }

        filesRef.current.set(localId, file);
        setUploads((current) => [
          ...current,
          { localId, folderId, filename: file.name, status: "uploading", canRetry: false },
        ]);
        start(localId, folderId, file);
      });
    },
    [start],
  );

  const retry = useCallback(
    (localId: string) => {
      const file = filesRef.current.get(localId);
      const upload = uploads.find((item) => item.localId === localId);
      if (file === undefined || upload === undefined) return;

      start(localId, upload.folderId, file);
    },
    [start, uploads],
  );

  const dismiss = useCallback((localId: string) => {
    filesRef.current.delete(localId);
    setUploads((current) => current.filter((upload) => upload.localId !== localId));
  }, []);

  return { uploads, addFiles, retry, dismiss };
};
