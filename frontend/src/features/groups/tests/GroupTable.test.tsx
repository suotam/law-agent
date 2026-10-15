import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import { server } from "@/test/msw/server";
import { renderWithProviders } from "@/test/render";
import { clearToken, setToken } from "@/features/auth";
import { GroupTable } from "@/features/groups";

const groups = [
  { id: "g1", name: "Klienti", created_at: "2026-08-01T00:00:00Z" },
  { id: "g2", name: "Paralegals", created_at: "2026-08-02T00:00:00Z" },
];

const groupsHandler = http.get("http://api.test/groups", () => HttpResponse.json(groups));

const signedInAs = (capabilities: string[]) => {
  setToken("token");
  server.use(
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
    ),
  );
};

describe("GroupTable", () => {
  afterEach(() => clearToken());

  it("renders every group by name", async () => {
    server.use(groupsHandler);

    renderWithProviders(<GroupTable />);

    expect(await screen.findByText("Klienti")).toBeInTheDocument();
    expect(screen.getByText("Paralegals")).toBeInTheDocument();
  });

  it("reports a failed listing", async () => {
    server.use(http.get("http://api.test/groups", () => new HttpResponse(null, { status: 500 })));

    renderWithProviders(<GroupTable />);

    expect(await screen.findByText("Skupiny se nepodařilo načíst.")).toBeInTheDocument();
  });

  it("hides the access-to-files button from a caller who only holds manage_groups", async () => {
    signedInAs(["manage_groups"]);
    server.use(groupsHandler);

    renderWithProviders(<GroupTable />);

    await screen.findByText("Klienti");
    expect(screen.queryByRole("link", { name: "Přístup skupiny Klienti" })).not.toBeInTheDocument();
  });

  it("shows the access-to-files button to a caller who also holds manage_org_files_structure", async () => {
    signedInAs(["manage_groups", "manage_org_files_structure"]);
    server.use(groupsHandler);

    renderWithProviders(<GroupTable />);

    const link = await screen.findByRole("link", { name: "Přístup skupiny Klienti" });
    expect(link).toHaveAttribute("href", "/admin/groups/g1/access");
  });
});
