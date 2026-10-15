import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";
import { server } from "@/test/msw/server";
import { renderWithProviders } from "@/test/render";
import { getScope, lockScope, SourceChips, useSourceScopeStore } from "@/features/sources";
import { useOrgFilesScopeStore } from "@/features/sources/org-files-scope-store";

// Toggling org_files on renders the OrgFilesScopePicker, which fetches the
// roots immediately -- every test below needs it stubbed, even the ones
// that only care about the chip's own on/off state.
const orgFilesPickerHandlers = [
  http.get("http://api.test/me/org-files/roots", () => HttpResponse.json([])),
];

describe("SourceChips", () => {
  beforeEach(() => {
    useSourceScopeStore.getState().reset();
    useOrgFilesScopeStore.getState().clear();
    server.use(...orgFilesPickerHandlers);
  });

  it("starts with nothing selected", () => {
    renderWithProviders(<SourceChips />);

    expect(screen.getByRole("button", { name: "Zákony" })).toHaveAttribute("aria-pressed", "false");
    expect(getScope()).toEqual([]);
  });

  it("toggles both chips independently", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SourceChips />);

    await user.click(screen.getByRole("button", { name: "Zákony" }));
    await user.click(screen.getByRole("button", { name: "Firemní soubory" }));
    expect(getScope()).toEqual(["laws", "org_files"]);

    await user.click(screen.getByRole("button", { name: "Zákony" }));
    expect(getScope()).toEqual(["org_files"]);
  });

  it("stops responding once the scope is locked", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SourceChips />);

    await user.click(screen.getByRole("button", { name: "Zákony" }));
    lockScope();
    await user.click(screen.getByRole("button", { name: "Firemní soubory" }));

    expect(getScope()).toEqual(["laws"]);
    expect(screen.getByRole("button", { name: "Firemní soubory" })).toBeDisabled();
  });

  it("clears the org files selection when org_files is toggled off", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SourceChips />);

    await user.click(screen.getByRole("button", { name: "Firemní soubory" }));
    useOrgFilesScopeStore.getState().toggleFolder("f1");
    await user.click(screen.getByRole("button", { name: "Firemní soubory" }));

    expect(useOrgFilesScopeStore.getState().folderIds).toEqual([]);
  });
});
