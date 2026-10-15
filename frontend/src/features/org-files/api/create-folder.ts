import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { FolderResponse } from "../types";
import { orgFileQueryKeys } from "./query-keys";

type CreateFolderRequest = {
  name: string;
  /** `null` creates a root folder, which the API accepts as an explicit null. */
  parent_id: string | null;
};

export const createFolder = async (payload: CreateFolderRequest): Promise<FolderResponse> => {
  const { data } = await apiClient.post<FolderResponse>("/folders", payload);
  return data;
};

export const useCreateFolder = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: createFolder,
    onSuccess: async (folder) => {
      await queryClient.invalidateQueries({
        queryKey: orgFileQueryKeys.level(folder.parent_id),
      });
    },
  });
};
