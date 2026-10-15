import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";
import { server } from "@/test/msw/server";
import { renderWithProviders } from "@/test/render";
import { OrgFilesScopePicker } from "@/features/sources";
import { useOrgFilesScopeStore } from "@/features/sources/org-files-scope-store";

const root = { id: "r1", name: "Litigation", ancestor_path: "Legal" };
const child = { id: "c1", parent_id: "r1", name: "2026", created_at: "2026-01-01T00:00:00Z" };
const secondChild = { id: "c3", parent_id: "r1", name: "2025", created_at: "2026-01-01T00:00:00Z" };
const grandchild = { id: "c2", parent_id: "c1", name: "Q1", created_at: "2026-01-01T00:00:00Z" };

const handlers = [
  http.get("http://api.test/me/org-files/roots", () => HttpResponse.json([root])),
  http.get("http://api.test/me/org-files/folders/r1", () =>
    HttpResponse.json({ folders: [child, secondChild], files: [] }),
  ),
  http.get("http://api.test/me/org-files/folders/c1", () =>
    HttpResponse.json({ folders: [grandchild], files: [] }),
  ),
  http.get("http://api.test/me/org-files/folders/c3", () =>
    HttpResponse.json({ folders: [], files: [] }),
  ),
];

describe("OrgFilesScopePicker", () => {
  beforeEach(() => {
    useOrgFilesScopeStore.getState().clear();
    server.use(...handlers);
  });

  it("checking a folder selects its already-loaded children", async () => {
    const user = userEvent.setup();
    renderWithProviders(<OrgFilesScopePicker />);

    // Expand first, so the child is already loaded when the root is checked.
    await user.click(await screen.findByText("Litigation"));
    const rootCheckbox = await screen.findByRole("checkbox", { name: "Vybrat složku Litigation" });
    const childCheckbox = await screen.findByRole("checkbox", { name: "Vybrat složku 2026" });
    await user.click(rootCheckbox);

    expect(childCheckbox).toBeChecked();
  });

  it("unchecking one child leaves the parent folder indeterminate", async () => {
    const user = userEvent.setup();
    renderWithProviders(<OrgFilesScopePicker />);

    await user.click(await screen.findByText("Litigation"));
    const rootCheckbox = await screen.findByRole("checkbox", { name: "Vybrat složku Litigation" });
    const childCheckbox = await screen.findByRole("checkbox", { name: "Vybrat složku 2026" });
    await user.click(rootCheckbox);
    await user.click(childCheckbox);

    expect(rootCheckbox).not.toBeChecked();
    expect((rootCheckbox as HTMLInputElement).indeterminate).toBe(true);
  });

  it("renders children of an already-checked folder as checked and disabled", async () => {
    const user = userEvent.setup();
    renderWithProviders(<OrgFilesScopePicker />);

    await user.click(await screen.findByText("Litigation"));
    const rootCheckbox = await screen.findByRole("checkbox", { name: "Vybrat složku Litigation" });
    await user.click(rootCheckbox);

    // Expand a child of the now-checked root -- its own children were not
    // loaded at check time, so they must be disabled on load instead.
    await user.click(await screen.findByText("2026"));
    const grandchildCheckbox = await screen.findByRole("checkbox", { name: "Vybrat složku Q1" });

    expect(grandchildCheckbox).toBeChecked();
    expect(grandchildCheckbox).toBeDisabled();
  });
});
