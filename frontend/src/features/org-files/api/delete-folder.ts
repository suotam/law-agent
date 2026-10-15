import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { orgFileQueryKeys } from "./query-keys";

export const deleteFolder = async (id: string): Promise<void> => {
  await apiClient.delete(`/folders/${id}`);
};

/** @param parentId the listing the deleted folder belongs to, i.e. the open location. */
export const useDeleteFolder = (parentId: string | null) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: deleteFolder,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: orgFileQueryKeys.level(parentId) });
    },
  });
};
