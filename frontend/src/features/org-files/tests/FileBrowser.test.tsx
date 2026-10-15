import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import { clearToken, setToken } from "@/features/auth";
import { server } from "@/test/msw/server";
import { renderWithProviders } from "@/test/render";
import { FileBrowser } from "../components/FileBrowser";
import { file, folder, level, orgFilesHandlers, root } from "./fixtures";

/** Roots: "Smlouvy" (f1). Inside f1: folder "2026" (f2) and one document. */
const libraryHandlers = orgFilesHandlers([root("f1", "Smlouvy")], {
  f1: level([folder("f2", "2026", "f1")], [file("d1", "smlouva.pdf")]),
});

const signedInAs = (capabilities: string[]) => {
  setToken("token");
  server.use(
    http.get("http://api.test/auth/me", () =>
      HttpResponse.json({
        id: "u1",
        email: "user@example.com",
        role: { id: "r1", name: "Member" },
        capabilities,
        is_superuser: false,
        is_active: true,
        created_at: "2026-08-01T00:00:00Z",
      }),
    ),
  );
};

describe("FileBrowser", () => {
  afterEach(() => clearToken());

  it("lists folders above files and descends on click", async () => {
    const user = userEvent.setup();
    server.use(...libraryHandlers);

    renderWithProviders(<FileBrowser />, { route: "/admin/files?path=f1" });

    const items = await screen.findAllByRole("listitem");
    expect(items[0]).toHaveTextContent("2026");
    expect(items[1]).toHaveTextContent("smlouva.pdf");

    await user.click(screen.getByRole("button", { name: "Otevřít složku 2026" }));

    expect(await screen.findByText("Složka je prázdná.")).toBeInTheDocument();
  });

  it("shows the ancestors in the breadcrumb and climbs back up", async () => {
    const user = userEvent.setup();
    server.use(...libraryHandlers);

    renderWithProviders(<FileBrowser />, { route: "/admin/files?path=f1/f2" });

    const breadcrumb = await screen.findByRole("navigation", { name: "Umístění" });
    expect(await screen.findByRole("button", { name: "Smlouvy" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Smlouvy" }));

    expect(await screen.findByText("smlouva.pdf")).toBeInTheDocument();
    expect(breadcrumb).toBeInTheDocument();
  });

  it("truncates the path when a folder in it no longer exists", async () => {
    server.use(...libraryHandlers);

    renderWithProviders(<FileBrowser />, { route: "/admin/files?path=f1/gone" });

    // "gone" is not among f1's children, so the browser falls back to f1 itself.
    expect(await screen.findByText("smlouva.pdf")).toBeInTheDocument();
  });

  it("shows only folders at the root", async () => {
    server.use(...libraryHandlers);

    renderWithProviders(<FileBrowser />, { route: "/admin/files" });

    expect(
      await screen.findByRole("button", { name: "Otevřít složku Smlouvy" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("smlouva.pdf")).not.toBeInTheDocument();
  });

  it("reports a failed listing", async () => {
    server.use(
      http.get("http://api.test/me/org-files/roots", () => new HttpResponse(null, { status: 500 })),
    );

    renderWithProviders(<FileBrowser />, { route: "/admin/files" });

    await waitFor(() =>
      expect(screen.getByText("Obsah složky se nepodařilo načíst.")).toBeInTheDocument(),
    );
  });

  it("opens the Share panel from a folder row action", async () => {
    const user = userEvent.setup();
    signedInAs(["manage_groups"]);
    server.use(
      ...libraryHandlers,
      http.get("http://api.test/acl/effective", () =>
        HttpResponse.json({ own: [], inherited: [] }),
      ),
      http.get("http://api.test/groups", () => HttpResponse.json([])),
      http.get("http://api.test/users", () => HttpResponse.json([])),
    );

    renderWithProviders(<FileBrowser />, { route: "/admin/files" });

    await user.click(await screen.findByRole("button", { name: "Akce položky" }));
    await user.click(screen.getByRole("menuitem", { name: "Sdílení" }));

    expect(await screen.findByRole("heading", { name: "Sdílení: Smlouvy" })).toBeInTheDocument();
  });

  it("opens the Share panel for a caller who only holds manage_users", async () => {
    const user = userEvent.setup();
    signedInAs(["manage_users"]);
    server.use(
      ...libraryHandlers,
      http.get("http://api.test/acl/effective", () =>
        HttpResponse.json({ own: [], inherited: [] }),
      ),
      http.get("http://api.test/groups", () => HttpResponse.json([])),
      http.get("http://api.test/users", () => HttpResponse.json([])),
    );

    renderWithProviders(<FileBrowser />, { route: "/admin/files" });

    await user.click(await screen.findByRole("button", { name: "Akce položky" }));
    await user.click(screen.getByRole("menuitem", { name: "Sdílení" }));

    expect(await screen.findByRole("heading", { name: "Sdílení: Smlouvy" })).toBeInTheDocument();
  });

  it("offers no sharing to a member without the groups capability", async () => {
    const user = userEvent.setup();
    signedInAs([]);
    server.use(...libraryHandlers);

    renderWithProviders(<FileBrowser />, { route: "/admin/files?path=f1" });

    // Only the document row has a menu at all: sharing and structure ops are both out of reach.
    await user.click(await screen.findByRole("button", { name: "Akce položky" }));

    expect(await screen.findByRole("menuitem", { name: "Stáhnout" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Sdílení" })).not.toBeInTheDocument();
  });
});

describe("FileBrowser permissions", () => {
  afterEach(() => clearToken());

  it("hides the upload button when the open folder is read-only", async () => {
    server.use(
      ...orgFilesHandlers([root("f1", "Smlouvy", { permission: "read" })], {
        f1: level([], [file("d1", "smlouva.pdf", { permission: "read" })]),
      }),
    );

    renderWithProviders(<FileBrowser />, { route: "/admin/files?path=f1" });

    await screen.findByText("smlouva.pdf");
    // The upload control is the file input inside the button's label.
    expect(screen.queryByLabelText("Nahrát soubor")).not.toBeInTheDocument();
  });

  it("shows the upload button when the open folder is writable", async () => {
    server.use(...orgFilesHandlers([root("f1", "Smlouvy", { permission: "write" })]));

    renderWithProviders(<FileBrowser />, { route: "/admin/files?path=f1" });

    expect(await screen.findByLabelText("Nahrát soubor")).toBeInTheDocument();
  });

  it("offers deleting a file only where the caller may write", async () => {
    const user = userEvent.setup();
    server.use(
      ...orgFilesHandlers([root("f1", "Smlouvy", { permission: "read" })], {
        f1: level(
          [],
          [
            file("d1", "cizi.pdf", { permission: "read" }),
            file("d2", "moje.pdf", { permission: "write" }),
          ],
        ),
      }),
    );

    renderWithProviders(<FileBrowser />, { route: "/admin/files?path=f1" });

    const menus = await screen.findAllByRole("button", { name: "Akce položky" });
    await user.click(menus[0]);
    expect(screen.queryByRole("menuitem", { name: "Smazat soubor" })).not.toBeInTheDocument();

    await user.click(menus[1]);
    expect(await screen.findByRole("menuitem", { name: "Smazat soubor" })).toBeInTheDocument();
  });

  it("shows structure actions only to a structure manager", async () => {
    const user = userEvent.setup();
    server.use(
      ...orgFilesHandlers([root("f1", "Smlouvy", { isStructureManager: true })], {
        f1: level([folder("f2", "2026", "f1", { isStructureManager: true })]),
      }),
    );

    renderWithProviders(<FileBrowser />, { route: "/admin/files?path=f1" });

    await screen.findByText("2026");
    expect(screen.getByRole("button", { name: "Nová složka" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Akce položky" }));
    expect(await screen.findByRole("menuitem", { name: "Přejmenovat" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Smazat složku" })).toBeInTheDocument();
  });

  it("hides structure actions from a member who may only write", async () => {
    server.use(
      ...orgFilesHandlers([root("f1", "Smlouvy", { permission: "write" })], {
        f1: level([folder("f2", "2026", "f1", { permission: "write" })]),
      }),
    );

    renderWithProviders(<FileBrowser />, { route: "/admin/files?path=f1" });

    await screen.findByText("2026");
    expect(screen.queryByRole("button", { name: "Nová složka" })).not.toBeInTheDocument();
    // Nothing is left for this row's menu: no structure ops, no sharing.
    expect(screen.queryByRole("button", { name: "Akce položky" })).not.toBeInTheDocument();
  });
});
