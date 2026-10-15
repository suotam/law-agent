import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import { server } from "@/test/msw/server";
import { renderWithProviders } from "@/test/render";
import { clearToken, setToken } from "@/features/auth";
import { SharePanel } from "@/features/groups";

const effective = {
  own: [
    {
      id: "acl1",
      resource_type: "folder",
      resource_id: "f1",
      principal_type: "group",
      principal_id: "g1",
      permission: "read",
      created_at: "2026-08-01T00:00:00Z",
    },
    {
      id: "acl3",
      resource_type: "folder",
      resource_id: "f1",
      principal_type: "user",
      principal_id: "u9",
      permission: "read",
      created_at: "2026-08-01T00:00:00Z",
    },
  ],
  inherited: [
    {
      id: "acl2",
      resource_type: "folder",
      resource_id: "parent",
      principal_type: "group",
      principal_id: "g2",
      permission: "read",
      created_at: "2026-08-01T00:00:00Z",
    },
  ],
};

const groupsHandler = http.get("http://api.test/groups", () =>
  HttpResponse.json([
    { id: "g1", name: "Klienti", created_at: "2026-08-01T00:00:00Z" },
    { id: "g2", name: "Paralegals", created_at: "2026-08-01T00:00:00Z" },
  ]),
);
const usersHandler = http.get("http://api.test/users", () =>
  HttpResponse.json([
    {
      id: "u9",
      email: "jana@firma.cz",
      role: { id: "r1", name: "Member" },
      capabilities: [],
      is_superuser: false,
      is_active: true,
      created_at: "2026-08-01T00:00:00Z",
    },
  ]),
);
const effectiveHandler = http.get("http://api.test/acl/effective", () =>
  HttpResponse.json(effective),
);

const meHandler = (capabilities: string[]) =>
  http.get("http://api.test/auth/me", () =>
    HttpResponse.json({
      id: "caller",
      email: "ja@firma.cz",
      role: { id: "r1", name: "Manager" },
      capabilities,
      is_superuser: false,
      is_active: true,
      created_at: "2026-08-01T00:00:00Z",
    }),
  );

const signedInAs = (capabilities: string[]) => {
  setToken("token");
  server.use(effectiveHandler, groupsHandler, usersHandler, meHandler(capabilities));
};

const renderPanel = (resourceType: "folder" | "document" = "folder") =>
  renderWithProviders(
    <SharePanel
      open
      onOpenChange={vi.fn()}
      resourceType={resourceType}
      resourceId={resourceType === "folder" ? "f1" : "d1"}
      resourceName={resourceType === "folder" ? "Smlouvy" : "a.pdf"}
    />,
  );

describe("SharePanel", () => {
  afterEach(() => clearToken());

  it("renders own and inherited grants in distinct sections, inherited with no remove control", async () => {
    signedInAs(["manage_groups", "manage_users"]);

    renderPanel();

    const ownSection = await screen.findByRole("region", { name: "Vlastní oprávnění" });
    expect(ownSection).toHaveTextContent("Klienti");
    const inheritedSection = screen.getByRole("region", { name: "Zděděná oprávnění" });
    expect(inheritedSection).toHaveTextContent("Paralegals");
    expect(
      within(inheritedSection).queryByRole("button", { name: /Odebrat/ }),
    ).not.toBeInTheDocument();
  });

  it("removes an own entry", async () => {
    const user = userEvent.setup();
    let deletedId: string | null = null;
    signedInAs(["manage_groups", "manage_users"]);
    server.use(
      http.delete("http://api.test/acl/:id", ({ params }) => {
        deletedId = params.id as string;
        return new HttpResponse(null, { status: 204 });
      }),
    );

    renderPanel();

    await user.click(await screen.findByRole("button", { name: "Odebrat oprávnění pro Klienti" }));

    expect(deletedId).toBe("acl1");
  });

  it("adds an entry via the search-select with the chosen principal and permission", async () => {
    const user = userEvent.setup();
    let posted: Record<string, unknown> | null = null;
    signedInAs(["manage_groups", "manage_users"]);
    server.use(
      http.post("http://api.test/acl", async ({ request }) => {
        posted = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(
          { id: "acl4", ...posted, created_at: "2026-09-05T00:00:00Z" },
          {
            status: 201,
          },
        );
      }),
    );

    renderPanel();

    await screen.findByRole("region", { name: "Vlastní oprávnění" });
    await user.selectOptions(screen.getByLabelText("Příjemce"), "g2");
    await user.selectOptions(screen.getByLabelText("Úroveň přístupu"), "write");
    await user.click(screen.getByRole("button", { name: "Přidat" }));

    expect(posted).toMatchObject({
      resource_type: "folder",
      resource_id: "f1",
      principal_type: "group",
      principal_id: "g2",
      permission: "write",
    });
  });

  it("only offers read permission when sharing a document", async () => {
    signedInAs(["manage_groups", "manage_users"]);

    renderPanel("document");

    const permissionSelect = await screen.findByLabelText("Úroveň přístupu");
    const options = within(permissionSelect)
      .getAllByRole("option")
      .map((o) => o.textContent);
    expect(options).toEqual(["Ke čtení"]);
  });

  it("shows a cascade warning when sharing a folder", async () => {
    signedInAs(["manage_groups", "manage_users"]);

    renderPanel();

    expect(await screen.findByText(/nastavení přístupu ke složce zruší/i)).toBeInTheDocument();
  });

  it("hides user grants entirely (own and inherited), and offers no principal-type choice, to a caller with only manage_groups", async () => {
    signedInAs(["manage_groups"]);

    renderPanel();

    const ownSection = await screen.findByRole("region", { name: "Vlastní oprávnění" });
    expect(screen.queryByText("Typ příjemce")).not.toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: "Uživatel" })).not.toBeInTheDocument();
    // The user grant "acl3" (jana@firma.cz) is gone entirely, not merely un-removable.
    expect(within(ownSection).queryByText("jana@firma.cz")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Odebrat oprávnění pro Klienti" }),
    ).toBeInTheDocument();
    // The candidate select only offers groups now.
    expect(screen.getByLabelText("Příjemce")).toHaveTextContent("Klienti");
    expect(screen.getByLabelText("Příjemce")).not.toHaveTextContent("jana@firma.cz");
  });

  it("hides group grants entirely (own and inherited), and offers no principal-type choice, to a caller with only manage_users", async () => {
    signedInAs(["manage_users"]);

    renderPanel();

    const ownSection = await screen.findByRole("region", { name: "Vlastní oprávnění" });
    const inheritedSection = screen.getByRole("region", { name: "Zděděná oprávnění" });
    expect(screen.queryByText("Typ příjemce")).not.toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: "Skupina" })).not.toBeInTheDocument();
    // The group grant "acl1" (Klienti) is gone entirely, not merely un-removable.
    expect(within(ownSection).queryByText("Klienti")).not.toBeInTheDocument();
    // The inherited group grant "acl2" (Paralegals) is hidden too.
    expect(within(inheritedSection).queryByText("Paralegals")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Odebrat oprávnění pro jana@firma.cz" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Příjemce")).toHaveTextContent("jana@firma.cz");
    expect(screen.getByLabelText("Příjemce")).not.toHaveTextContent("Klienti");
  });

  it("shows the empty-own message when the only own grant is hidden by capability", async () => {
    signedInAs(["manage_groups"]);
    server.use(
      http.get("http://api.test/acl/effective", () =>
        HttpResponse.json({
          own: [
            {
              id: "acl3",
              resource_type: "folder",
              resource_id: "f1",
              principal_type: "user",
              principal_id: "u9",
              permission: "read",
              created_at: "2026-08-01T00:00:00Z",
            },
          ],
          inherited: [],
        }),
      ),
    );

    renderPanel();

    expect(await screen.findByText("Zatím žádná vlastní oprávnění.")).toBeInTheDocument();
  });
});
