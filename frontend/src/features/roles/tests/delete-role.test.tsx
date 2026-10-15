import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "@/test/msw/server";
import { renderWithProviders } from "@/test/render";
import { RolesScreen } from "@/features/roles";

const role = {
  id: "r2",
  name: "Files Manager",
  is_superuser: false,
  capabilities: ["manage_org_files_structure"],
  created_at: "2026-08-02T00:00:00Z",
};

const listing = [http.get("http://api.test/roles", () => HttpResponse.json([role]))];

describe("role deletion", () => {
  it("deletes a role and removes it from the list", async () => {
    const user = userEvent.setup();
    let roles: (typeof role)[] = [role];
    server.use(
      http.get("http://api.test/roles", () => HttpResponse.json(roles)),
      http.delete("http://api.test/roles/r2", () => {
        roles = [];
        return new HttpResponse(null, { status: 204 });
      }),
    );

    renderWithProviders(<RolesScreen />);

    await user.click(await screen.findByRole("button", { name: "Smazat roli Files Manager" }));
    await user.click(await screen.findByRole("button", { name: "Smazat" }));

    expect(screen.queryByText("Files Manager")).not.toBeInTheDocument();
  });

  it("surfaces a 409 inline and keeps the dialog open", async () => {
    const user = userEvent.setup();
    server.use(
      ...listing,
      http.delete("http://api.test/roles/r2", () =>
        HttpResponse.json({ detail: "role still in use" }, { status: 409 }),
      ),
    );

    renderWithProviders(<RolesScreen />);

    await user.click(await screen.findByRole("button", { name: "Smazat roli Files Manager" }));
    await user.click(await screen.findByRole("button", { name: "Smazat" }));

    expect(
      await screen.findByText("Roli nelze smazat, je stále přiřazena uživateli."),
    ).toBeInTheDocument();
    expect(screen.getByText("Files Manager")).toBeInTheDocument();
  });
});
