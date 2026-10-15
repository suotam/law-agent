import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "@/test/msw/server";
import { renderWithProviders } from "@/test/render";
import { RoleTable } from "@/features/roles";

const roles = [
  {
    id: "r1",
    name: "Admin",
    is_superuser: true,
    capabilities: ["manage_users", "manage_groups", "manage_org_files_structure"],
    created_at: "2026-08-01T00:00:00Z",
  },
  {
    id: "r2",
    name: "Files Manager",
    is_superuser: false,
    capabilities: ["manage_org_files_structure"],
    created_at: "2026-08-02T00:00:00Z",
  },
];

describe("RoleTable", () => {
  it("renders roles with a superuser badge and capability chips", async () => {
    server.use(http.get("http://api.test/roles", () => HttpResponse.json(roles)));

    renderWithProviders(<RoleTable />);

    expect(await screen.findByText("Admin")).toBeInTheDocument();
    expect(await screen.findByText("Files Manager")).toBeInTheDocument();
    expect(screen.getAllByText("Superuživatel")).toHaveLength(1);
    expect(screen.getAllByText("Správa firemních souborů")).toHaveLength(2);
    expect(screen.getByText("Správa uživatelů")).toBeInTheDocument();
  });

  it("offers no edit or delete on a superuser role, even with handlers given", async () => {
    server.use(http.get("http://api.test/roles", () => HttpResponse.json(roles)));

    renderWithProviders(
      <RoleTable
        onEdit={() => undefined}
        onDelete={() => undefined}
      />,
    );

    expect(await screen.findByText("Admin")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Upravit roli Admin" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Smazat roli Admin" })).not.toBeInTheDocument();
    // The non-superuser role keeps its actions.
    expect(screen.getByRole("button", { name: "Upravit roli Files Manager" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Smazat roli Files Manager" })).toBeInTheDocument();
  });

  it("shows the load error message on failure", async () => {
    server.use(http.get("http://api.test/roles", () => HttpResponse.error()));

    renderWithProviders(<RoleTable />);

    expect(await screen.findByText("Role se nepodařilo načíst.")).toBeInTheDocument();
  });
});
