import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { FolderItem, FolderLevel } from "../types";
import { orgFileQueryKeys } from "./query-keys";

/** The caller's topmost visible folders; no document lives at this level. */
export const listRoots = async (): Promise<FolderItem[]> => {
  const { data } = await apiClient.get<FolderItem[]>("/me/org-files/roots");
  return data;
};

export const getFolderContents = async (folderId: string): Promise<FolderLevel> => {
  const { data } = await apiClient.get<FolderLevel>(`/me/org-files/folders/${folderId}`);
  return data;
};

/*
 * Reads go through the member endpoints for everyone, structure managers
 * included: they resolve to full access on the server, so one code path
 * serves both. The admin `/folders` routes stay for structure mutations only.
 */
/**
 * `enabled` defaults to true (the single-level browser always wants its
 * current level); the scope picker's tree passes `isOpen` per node so a
 * collapsed folder's contents are never fetched.
 */
export const useFolderLevel = (folderId: string | null, enabled = true) =>
  useQuery({
    queryKey: orgFileQueryKeys.level(folderId),
    queryFn: async (): Promise<FolderLevel> =>
      folderId === null ? { folders: await listRoots(), files: [] } : getFolderContents(folderId),
    enabled,
  });
