import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { orgFileQueryKeys } from "./query-keys";

async function deleteDocument(documentId: string): Promise<void> {
  await apiClient.delete(`/me/org-files/documents/${documentId}`);
}

/** @param folderId the listing the deleted document belongs to, i.e. the open location. */
export function useDeleteDocument(folderId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteDocument,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: orgFileQueryKeys.level(folderId) }),
  });
}
