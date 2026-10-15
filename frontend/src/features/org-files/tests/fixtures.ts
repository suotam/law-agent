import { http, HttpResponse } from "msw";
import type {
  EffectivePermission,
  FolderItem,
  FolderLevel,
  FolderResponse,
  OrgFileResponse,
} from "../types";

/** What the server reports about the caller's access to one node. */
type Access = {
  permission?: EffectivePermission | null;
  isStructureManager?: boolean;
};

const access = ({ permission = "write", isStructureManager = false }: Access) => ({
  effective_permission: permission,
  is_structure_manager: isStructureManager,
});

export const root = (id: string, name: string, granted: Access = {}): FolderItem => ({
  id,
  name,
  ancestor_path: "",
  ...access(granted),
});

export const folder = (
  id: string,
  name: string,
  parentId: string | null,
  granted: Access = {},
): FolderResponse => ({
  id,
  name,
  parent_id: parentId,
  created_at: "2026-08-01T00:00:00Z",
  ...access(granted),
});

export const file = (id: string, filename: string, granted: Access = {}): OrgFileResponse => ({
  id,
  filename,
  mime: "application/pdf",
  byte_size: 2048,
  status: "indexed",
  ...access(granted),
});

export const level = (folders: FolderItem[] = [], files: OrgFileResponse[] = []): FolderLevel => ({
  folders,
  files,
});

/** The two member read endpoints the browser lives on. A folder with no
 * entry in `contents` answers as an empty folder, which is what the real
 * API does for a leaf. */
export const orgFilesHandlers = (
  roots: FolderItem[],
  contents: Record<string, FolderLevel> = {},
) => [
  http.get("http://api.test/me/org-files/roots", () => HttpResponse.json(roots)),
  http.get("http://api.test/me/org-files/folders/:folderId", ({ params }) =>
    HttpResponse.json(contents[params.folderId as string] ?? level()),
  ),
];
