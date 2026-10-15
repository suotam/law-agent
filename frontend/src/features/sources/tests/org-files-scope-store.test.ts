import { beforeEach, describe, expect, it } from "vitest";
import { useOrgFilesScopeStore } from "../org-files-scope-store";

describe("useOrgFilesScopeStore", () => {
  beforeEach(() => {
    useOrgFilesScopeStore.getState().clear();
  });

  it("starts with both lists empty", () => {
    const state = useOrgFilesScopeStore.getState();
    expect(state.folderIds).toEqual([]);
    expect(state.documentIds).toEqual([]);
  });

  it("toggles a folder id on and off", () => {
    const { toggleFolder } = useOrgFilesScopeStore.getState();
    toggleFolder("f1");
    expect(useOrgFilesScopeStore.getState().folderIds).toEqual(["f1"]);
    toggleFolder("f1");
    expect(useOrgFilesScopeStore.getState().folderIds).toEqual([]);
  });

  it("sets a folder's checked state explicitly, without duplicating an id", () => {
    const { setFolderChecked } = useOrgFilesScopeStore.getState();
    setFolderChecked("f1", true);
    setFolderChecked("f1", true);
    expect(useOrgFilesScopeStore.getState().folderIds).toEqual(["f1"]);
    setFolderChecked("f1", false);
    expect(useOrgFilesScopeStore.getState().folderIds).toEqual([]);
  });

  it("toggles a document id independently of folders", () => {
    const { toggleDocument } = useOrgFilesScopeStore.getState();
    toggleDocument("d1");
    expect(useOrgFilesScopeStore.getState().documentIds).toEqual(["d1"]);
  });

  it("clear empties both lists and unlocks", () => {
    const { toggleFolder, toggleDocument, lock, clear } = useOrgFilesScopeStore.getState();
    toggleFolder("f1");
    toggleDocument("d1");
    lock();

    clear();

    const state = useOrgFilesScopeStore.getState();
    expect(state.folderIds).toEqual([]);
    expect(state.documentIds).toEqual([]);
    expect(state.isLocked).toBe(false);
  });

  it("ignores toggles once locked", () => {
    const { toggleFolder, lock } = useOrgFilesScopeStore.getState();
    lock();
    toggleFolder("f1");
    expect(useOrgFilesScopeStore.getState().folderIds).toEqual([]);
  });
});
