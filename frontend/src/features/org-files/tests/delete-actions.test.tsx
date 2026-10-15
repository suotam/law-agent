import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { server } from "@/test/msw/server";
import { renderWithProviders } from "@/test/render";
import { FileBrowser } from "../components/FileBrowser";
import { file, folder, level, orgFilesHandlers, root } from "./fixtures";

/** Inside f1 sits one folder and one document, so both row menus are on screen
 * at once; the caller manages the structure, so every action is offered. */
const listing = orgFilesHandlers([root("f1", "Smlouvy", { isStructureManager: true })], {
  f1: level(
    [folder("f2", "2026", "f1", { isStructureManager: true })],
    [file("d1", "smlouva.pdf", { isStructureManager: true })],
  ),
});

describe("delete actions", () => {
  it("deletes an empty folder after confirmation", async () => {
    const user = userEvent.setup();
    const deleted = vi.fn();
    server.use(
      ...listing,
      http.delete("http://api.test/folders/f2", () => {
        deleted();
        return new HttpResponse(null, { status: 204 });
      }),
    );

    renderWithProviders(<FileBrowser />, { route: "/admin/files?path=f1" });

    const menus = await screen.findAllByRole("button", { name: "Akce položky" });
    await user.click(menus[0]);
    await user.click(await screen.findByRole("menuitem", { name: "Smazat složku" }));
    await user.click(await screen.findByRole("button", { name: "Smazat" }));

    await waitFor(() => expect(deleted).toHaveBeenCalledTimes(1));
  });

  it("explains why a non-empty folder cannot be deleted and stays open", async () => {
    const user = userEvent.setup();
    server.use(
      ...listing,
      http.delete("http://api.test/folders/f2", () =>
        HttpResponse.json({ detail: "folder not empty" }, { status: 409 }),
      ),
    );

    renderWithProviders(<FileBrowser />, { route: "/admin/files?path=f1" });

    const menus = await screen.findAllByRole("button", { name: "Akce položky" });
    await user.click(menus[0]);
    await user.click(await screen.findByRole("menuitem", { name: "Smazat složku" }));
    await user.click(await screen.findByRole("button", { name: "Smazat" }));

    expect(
      await screen.findByText("Složku nelze smazat, obsahuje soubory nebo podsložky."),
    ).toBeInTheDocument();
  });

  it("deletes a file through the member endpoint after confirmation", async () => {
    const user = userEvent.setup();
    const deleted = vi.fn();
    server.use(
      ...listing,
      http.delete("http://api.test/me/org-files/documents/d1", () => {
        deleted();
        return new HttpResponse(null, { status: 204 });
      }),
    );

    renderWithProviders(<FileBrowser />, { route: "/admin/files?path=f1" });

    const menus = await screen.findAllByRole("button", { name: "Akce položky" });
    await user.click(menus[1]);
    await user.click(await screen.findByRole("menuitem", { name: "Smazat soubor" }));
    await user.click(await screen.findByRole("button", { name: "Smazat" }));

    await waitFor(() => expect(deleted).toHaveBeenCalledTimes(1));
  });
});
