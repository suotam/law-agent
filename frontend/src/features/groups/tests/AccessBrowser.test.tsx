import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { renderWithProviders } from "@/test/render";
import { AccessBrowser } from "@/features/groups";
import type { AclEntryResponse } from "@/features/groups";
import { file, folder, level, orgFilesHandlers, root } from "@/features/org-files/tests/fixtures";
import { server } from "@/test/msw/server";
import { http, HttpResponse } from "msw";

const managed = { isStructureManager: true };

const aclOf = (entries: AclEntryResponse[], foldersWithNestedGrant: string[] = []) => ({
  data: { entries, folders_with_nested_grant: foldersWithNestedGrant },
  isPending: false,
  isError: false,
});

const grant = (overrides: Partial<AclEntryResponse> = {}): AclEntryResponse => ({
  id: "acl1",
  resource_type: "folder",
  resource_id: "f1",
  principal_type: "group",
  principal_id: "g1",
  permission: "read",
  created_at: "2026-08-01T00:00:00Z",
  ...overrides,
});

describe("AccessBrowser", () => {
  it("shows a page heading naming the principal", async () => {
    server.use(...orgFilesHandlers([root("f1", "Smlouvy", managed)]));

    renderWithProviders(
      <AccessBrowser
        principalType="group"
        principalId="g1"
        principalName="Klienti"
        acl={aclOf([])}
      />,
      { route: "/?path=" },
    );

    expect(await screen.findByRole("heading", { name: "Přístup: Klienti" })).toBeInTheDocument();
  });

  it("marks a folder with no grant of its own as containing a nested grant", async () => {
    server.use(...orgFilesHandlers([root("f1", "Smlouvy", managed)]));

    renderWithProviders(
      <AccessBrowser
        principalType="group"
        principalId="g1"
        principalName="Klienti"
        acl={aclOf([], ["f1"])}
      />,
      { route: "/?path=" },
    );

    await screen.findByRole("button", { name: "Přístup ke složce Smlouvy: Bez přístupu" });
    expect(screen.getByText("obsahuje sdílené položky")).toBeInTheDocument();
  });

  it("does not mark a folder with its own grant as containing a nested grant", async () => {
    server.use(...orgFilesHandlers([root("f1", "Smlouvy", managed)]));

    renderWithProviders(
      <AccessBrowser
        principalType="group"
        principalId="g1"
        principalName="Klienti"
        acl={aclOf([grant()], ["f1"])}
      />,
      { route: "/?path=" },
    );

    await screen.findByRole("button", { name: "Přístup ke složce Smlouvy: Ke čtení" });
    expect(screen.queryByText("obsahuje sdílené položky")).not.toBeInTheDocument();
  });

  it("does not mark a document as containing a nested grant", async () => {
    server.use(
      ...orgFilesHandlers([root("f1", "Smlouvy", managed)], {
        f1: level([], [file("d1", "smlouva.pdf", managed)]),
      }),
    );

    renderWithProviders(
      <AccessBrowser
        principalType="group"
        principalId="g1"
        principalName="Klienti"
        acl={aclOf([], ["d1"])}
      />,
      { route: "/?path=f1" },
    );

    await screen.findByRole("button", { name: "Přístup ke složce smlouva.pdf: Bez přístupu" });
    expect(screen.queryByText("obsahuje sdílené položky")).not.toBeInTheDocument();
  });

  it("shows a directly granted folder's own read state, not disabled", async () => {
    server.use(...orgFilesHandlers([root("f1", "Smlouvy", managed)]));

    renderWithProviders(
      <AccessBrowser
        principalType="group"
        principalId="g1"
        principalName="Klienti"
        acl={aclOf([grant()])}
      />,
      { route: "/?path=" },
    );

    const button = await screen.findByRole("button", {
      name: "Přístup ke složce Smlouvy: Ke čtení",
    });
    expect(button).not.toBeDisabled();
  });

  it("shows a child folder with no own grant as inherited-read and disabled, via the ancestor", async () => {
    server.use(
      ...orgFilesHandlers([root("f1", "Smlouvy", managed)], {
        f1: level([folder("f2", "2026", "f1", managed)]),
      }),
    );

    renderWithProviders(
      <AccessBrowser
        principalType="group"
        principalId="g1"
        principalName="Klienti"
        acl={aclOf([grant()])}
      />,
      { route: "/?path=f1" },
    );

    const button = await screen.findByRole("button", { name: "Přístup ke složce 2026: Ke čtení" });
    expect(button).toBeDisabled();
    expect(await screen.findByText("přes Smlouvy")).toBeInTheDocument();
  });

  it("posts a read grant using the given principal when clicking a folder with no grant at all", async () => {
    const user = userEvent.setup();
    let posted: Record<string, unknown> | null = null;
    server.use(
      ...orgFilesHandlers([root("f3", "Judikatura", managed)]),
      http.post("http://api.test/acl", async ({ request }) => {
        posted = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(
          { id: "acl3", ...posted, created_at: "2026-09-05T00:00:00Z" },
          {
            status: 201,
          },
        );
      }),
    );

    renderWithProviders(
      <AccessBrowser
        principalType="user"
        principalId="u1"
        principalName="Jana Nováková"
        acl={aclOf([])}
      />,
      { route: "/?path=" },
    );

    const button = await screen.findByRole("button", {
      name: "Přístup ke složce Judikatura: Bez přístupu",
    });
    await user.click(button);

    expect(posted).toMatchObject({
      resource_type: "folder",
      resource_id: "f3",
      principal_type: "user",
      principal_id: "u1",
      permission: "read",
    });
  });

  it("upgrades an existing read grant to write on a second click", async () => {
    const user = userEvent.setup();
    let posted: Record<string, unknown> | null = null;
    server.use(
      ...orgFilesHandlers([root("f1", "Smlouvy", managed)]),
      http.post("http://api.test/acl", async ({ request }) => {
        posted = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(
          { id: "acl1", ...posted, created_at: "2026-09-05T00:00:00Z" },
          {
            status: 201,
          },
        );
      }),
    );

    renderWithProviders(
      <AccessBrowser
        principalType="group"
        principalId="g1"
        principalName="Klienti"
        acl={aclOf([grant()])}
      />,
      { route: "/?path=" },
    );

    const button = await screen.findByRole("button", {
      name: "Přístup ke složce Smlouvy: Ke čtení",
    });
    await user.click(button);

    expect(posted).toMatchObject({
      resource_type: "folder",
      resource_id: "f1",
      principal_type: "group",
      principal_id: "g1",
      permission: "write",
    });
  });

  it("shows a document with no own grant as inherited-read and disabled, via its folder's grant", async () => {
    server.use(
      ...orgFilesHandlers([root("f1", "Smlouvy", managed)], {
        f1: level([], [file("d1", "smlouva.pdf", managed)]),
      }),
    );

    renderWithProviders(
      <AccessBrowser
        principalType="group"
        principalId="g1"
        principalName="Klienti"
        acl={aclOf([grant()])}
      />,
      { route: "/?path=f1" },
    );

    const button = await screen.findByRole("button", {
      name: "Přístup ke složce smlouva.pdf: Ke čtení",
    });
    expect(button).toBeDisabled();
    expect(await screen.findByText("přes Smlouvy")).toBeInTheDocument();
  });

  it("deletes an own write grant when clicking a checked, non-inherited row a third time", async () => {
    const user = userEvent.setup();
    let deletedId: string | null = null;
    server.use(
      ...orgFilesHandlers([root("f1", "Smlouvy", managed)]),
      http.delete("http://api.test/acl/:id", ({ params }) => {
        deletedId = params.id as string;
        return new HttpResponse(null, { status: 204 });
      }),
    );

    renderWithProviders(
      <AccessBrowser
        principalType="group"
        principalId="g1"
        principalName="Klienti"
        acl={aclOf([grant({ permission: "write" })])}
      />,
      { route: "/?path=" },
    );

    const button = await screen.findByRole("button", {
      name: "Přístup ke složce Smlouvy: Ke čtení a zápisu",
    });
    await user.click(button);

    expect(deletedId).toBe("acl1");
  });

  it("deletes an own read grant on a document instead of upgrading it to write", async () => {
    const user = userEvent.setup();
    let posted: Record<string, unknown> | null = null;
    let deletedId: string | null = null;
    server.use(
      ...orgFilesHandlers([root("f1", "Smlouvy", managed)], {
        f1: level([], [file("d1", "smlouva.pdf", managed)]),
      }),
      http.post("http://api.test/acl", async ({ request }) => {
        posted = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(
          { id: "acl1", ...posted, created_at: "2026-09-05T00:00:00Z" },
          {
            status: 201,
          },
        );
      }),
      http.delete("http://api.test/acl/:id", ({ params }) => {
        deletedId = params.id as string;
        return new HttpResponse(null, { status: 204 });
      }),
    );

    renderWithProviders(
      <AccessBrowser
        principalType="group"
        principalId="g1"
        principalName="Klienti"
        acl={aclOf([grant({ resource_type: "document", resource_id: "d1" })])}
      />,
      { route: "/?path=f1" },
    );

    const button = await screen.findByRole("button", {
      name: "Přístup ke složce smlouva.pdf: Ke čtení",
    });
    await user.click(button);

    expect(deletedId).toBe("acl1");
    expect(posted).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Přístup ke složce smlouva.pdf: Ke čtení a zápisu" }),
    ).not.toBeInTheDocument();
  });

  it("warns that granting a folder clears deeper individual grants", async () => {
    server.use(...orgFilesHandlers([root("f1", "Smlouvy", managed)]));

    renderWithProviders(
      <AccessBrowser
        principalType="group"
        principalId="g1"
        principalName="Klienti"
        acl={aclOf([grant()])}
      />,
      { route: "/?path=" },
    );

    await screen.findByRole("button", { name: "Přístup ke složce Smlouvy: Ke čtení" });
    expect(
      screen.getByText(/nastavení nebo zrušení přístupu ke složce zruší/i),
    ).toBeInTheDocument();
  });
});
