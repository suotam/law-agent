export type EffectivePermission = "read" | "write";

/**
 * What a folder row needs to render and to gate its actions. Both listings
 * produce rows of this shape: a virtual root (`/me/org-files/roots`, which
 * carries `ancestor_path` and no parent) and a child folder
 * (`/me/org-files/folders/{id}`, which carries a parent and a creation time).
 */
export type FolderItem = {
  id: string;
  name: string;
  effective_permission: EffectivePermission | null;
  /** A property of the caller, not of the node: the same on every row. */
  is_structure_manager: boolean;
  /** Roots only: the real chain above them, as context text -- never browsable. */
  ancestor_path?: string;
};

export type FolderResponse = FolderItem & {
  parent_id: string | null;
  created_at: string;
};

/** Same shape the chat attachment upload returns; `status` is informational only. */
export type OrgFileResponse = {
  id: string;
  filename: string;
  mime: string;
  byte_size: number;
  status: string;
  effective_permission: EffectivePermission | null;
  is_structure_manager: boolean;
};

/** One level of the browser: `GET /me/org-files/folders/{id}` verbatim, and
 * the roots listing widened into the same shape (roots hold no documents). */
export type FolderLevel = {
  folders: FolderItem[];
  files: OrgFileResponse[];
};
