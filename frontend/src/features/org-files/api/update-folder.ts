import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { FolderResponse } from "../types";
import { orgFileQueryKeys } from "./query-keys";

type UpdateFolderRequest = {
  id: string;
  name: string;
};

export const updateFolder = async ({ id, name }: UpdateFolderRequest): Promise<FolderResponse> => {
  // PATCH leaves out what does not change; only the name is ever edited here.
  const { data } = await apiClient.patch<FolderResponse>(`/folders/${id}`, { name });
  return data;
};

export const useUpdateFolder = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: updateFolder,
    onSuccess: async (folder) => {
      await queryClient.invalidateQueries({
        queryKey: orgFileQueryKeys.level(folder.parent_id),
      });
    },
  });
};
