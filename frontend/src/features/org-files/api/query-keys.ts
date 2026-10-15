/*
 * Kept apart from the endpoint files: a mutation invalidates a key that belongs to a query in
 * another file, and a shared home stops those two files importing each other.
 */
const roots = ["org-files", "roots"] as const;

const folder = (folderId: string) => ["org-files", "folder", folderId] as const;

export const orgFileQueryKeys = {
  roots,
  folder,
  /** The listing shown at one level of the tree: the caller's roots at the
   * top, one folder's contents below. Folders and documents share it -- a
   * single response carries both. */
  level: (folderId: string | null) => (folderId === null ? roots : folder(folderId)),
};
