import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { server } from "@/test/msw/server";
import { renderWithProviders } from "@/test/render";
import { FileBrowser } from "../components/FileBrowser";
import type { FolderResponse } from "../types";
import { folder, level, orgFilesHandlers, root } from "./fixtures";

const managed = { isStructureManager: true };

/*
 * The root always holds "f1", the folder these tests work inside: an id the root does not list
 * is treated as deleted and the browser truncates the path back to the root. Structure
 * operations need the capability, so every node reports the caller as a structure manager.
 */
const listing = (children: FolderResponse[]) =>
  orgFilesHandlers([root("f1", "Smlouvy", managed)], { f1: level(children) });

describe("folder actions", () => {
  it("creates a folder in the open location", async () => {
    const user = userEvent.setup();
    const created = vi.fn();
    server.use(
      ...listing([]),
      http.post("http://api.test/folders", async ({ request }) => {
        created(await request.json());
        return HttpResponse.json(folder("f9", "Smlouvy", "f1", managed), { status: 201 });
      }),
    );

    renderWithProviders(<FileBrowser />, { route: "/admin/files?path=f1" });

    await user.click(await screen.findByRole("button", { name: "Nová složka" }));
    await user.type(screen.getByLabelText("Název složky"), "Smlouvy");
    await user.click(screen.getByRole("button", { name: "Vytvořit" }));

    await waitFor(() => expect(created).toHaveBeenCalledWith({ name: "Smlouvy", parent_id: "f1" }));
  });

  it("keeps the dialog open and names the conflict when the name is taken", async () => {
    const user = userEvent.setup();
    server.use(
      ...listing([]),
      http.post("http://api.test/folders", () =>
        HttpResponse.json({ detail: "folder exists" }, { status: 409 }),
      ),
    );

    renderWithProviders(<FileBrowser />, { route: "/admin/files?path=f1" });

    await user.click(await screen.findByRole("button", { name: "Nová složka" }));
    await user.type(screen.getByLabelText("Název složky"), "Smlouvy");
    await user.click(screen.getByRole("button", { name: "Vytvořit" }));

    expect(await screen.findByText("Složka s tímto jménem už tady je.")).toBeInTheDocument();
    expect(screen.getByLabelText("Název složky")).toBeInTheDocument();
  });

  it("renames a folder from its row menu", async () => {
    const user = userEvent.setup();
    const renamed = vi.fn();
    server.use(
      ...listing([folder("f2", "2026", "f1", managed)]),
      http.patch("http://api.test/folders/f2", async ({ request }) => {
        renamed(await request.json());
        return HttpResponse.json(folder("f2", "2027", "f1", managed));
      }),
    );

    renderWithProviders(<FileBrowser />, { route: "/admin/files?path=f1" });

    await user.click(await screen.findByRole("button", { name: "Akce položky" }));
    await user.click(await screen.findByRole("menuitem", { name: "Přejmenovat" }));

    const input = screen.getByLabelText("Název složky");
    await user.clear(input);
    await user.type(input, "2027");
    await user.click(screen.getByRole("button", { name: "Uložit" }));

    await waitFor(() => expect(renamed).toHaveBeenCalledWith({ name: "2027" }));
  });

  it("refuses an empty name without calling the API", async () => {
    const user = userEvent.setup();
    const created = vi.fn();
    server.use(
      ...listing([]),
      http.post("http://api.test/folders", () => {
        created();
        return HttpResponse.json(folder("f9", "x", null, managed), { status: 201 });
      }),
    );

    renderWithProviders(<FileBrowser />, { route: "/admin/files" });

    await user.click(await screen.findByRole("button", { name: "Nová složka" }));
    await user.click(screen.getByRole("button", { name: "Vytvořit" }));

    expect(await screen.findByText("Zadejte název složky.")).toBeInTheDocument();
    expect(created).not.toHaveBeenCalled();
  });
});
