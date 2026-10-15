import { useCallback, useState } from "react";
import { apiClient } from "@/lib/api-client";
import type { OrgFileResponse } from "../types";

export const downloadDocument = async (id: string): Promise<Blob> => {
  // Not a plain <a href>: the endpoint needs the bearer header, which a navigation cannot send.
  const { data } = await apiClient.get<Blob>(`/me/org-files/documents/${id}/download`, {
    responseType: "blob",
    timeout: 0,
  });

  return data;
};

export const useDownloadDocument = () => {
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [hasFailed, setHasFailed] = useState(false);

  const download = useCallback(async (file: OrgFileResponse) => {
    setDownloadingId(file.id);
    setHasFailed(false);

    try {
      const blob = await downloadDocument(file.id);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");

      anchor.href = url;
      // The name is already known from the listing, so Content-Disposition needs no parsing.
      anchor.download = file.filename;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch {
      setHasFailed(true);
    } finally {
      setDownloadingId(null);
    }
  }, []);

  return { download, downloadingId, hasFailed };
};
