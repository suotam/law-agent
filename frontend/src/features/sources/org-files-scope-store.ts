import { create } from "zustand";

type OrgFilesScopeState = {
  folderIds: string[];
  documentIds: string[];
  /** True once the conversation exists: mirrors `isLocked` in
   * `source-scope-store.ts` -- a frozen conversation cannot change what it
   * searches mid-thread. */
  isLocked: boolean;
  toggleFolder: (id: string) => void;
  /** Explicit set/unset, for the tree's "check all currently-loaded children"
   * behaviour, where a plain toggle would be ambiguous about direction. */
  setFolderChecked: (id: string, isChecked: boolean) => void;
  toggleDocument: (id: string) => void;
  lock: () => void;
  /** Empties both lists and unlocks -- called when `org_files` is toggled
   * off, so a re-enabled picker starts from a clean slate rather than a
   * stale selection nobody can see any more. */
  clear: () => void;
};

const toggleId = (ids: string[], id: string): string[] =>
  ids.includes(id) ? ids.filter((entry) => entry !== id) : [...ids, id];

const setId = (ids: string[], id: string, isChecked: boolean): string[] => {
  const withoutId = ids.filter((entry) => entry !== id);
  return isChecked ? [...withoutId, id] : withoutId;
};

export const useOrgFilesScopeStore = create<OrgFilesScopeState>()((set) => ({
  folderIds: [],
  documentIds: [],
  isLocked: false,
  toggleFolder: (id) =>
    set((state) => (state.isLocked ? state : { folderIds: toggleId(state.folderIds, id) })),
  setFolderChecked: (id, isChecked) =>
    set((state) => (state.isLocked ? state : { folderIds: setId(state.folderIds, id, isChecked) })),
  toggleDocument: (id) =>
    set((state) => (state.isLocked ? state : { documentIds: toggleId(state.documentIds, id) })),
  lock: () => set({ isLocked: true }),
  clear: () => set({ folderIds: [], documentIds: [], isLocked: false }),
}));

export const getOrgFilesScope = (): { folderIds: string[]; documentIds: string[] } => {
  const { folderIds, documentIds } = useOrgFilesScopeStore.getState();
  return { folderIds, documentIds };
};

export const lockOrgFilesScope = (): void => useOrgFilesScopeStore.getState().lock();
