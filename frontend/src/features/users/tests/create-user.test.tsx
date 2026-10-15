import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "@/test/msw/server";
import { renderWithProviders } from "@/test/render";
import { UsersScreen } from "@/features/users";

const roles = [
  {
    id: "r1",
    name: "Admin",
    is_superuser: true,
    capabilities: [],
    created_at: "2026-08-01T00:00:00Z",
  },
  {
    id: "r2",
    name: "Member",
    is_superuser: false,
    capabilities: [],
    created_at: "2026-08-01T00:00:00Z",
  },
];

const listing = [
  http.get("http://api.test/roles", () => HttpResponse.json(roles)),
  http.get("http://api.test/users", () => HttpResponse.json([])),
];

describe("CreateUserDialog", () => {
  it("creates a user and closes the dialog", async () => {
    const user = userEvent.setup();
    server.use(
      ...listing,
      http.post("http://api.test/users", () =>
        HttpResponse.json(
          {
            id: "u2",
            email: "novy@firma.cz",
            role: { id: "r2", name: "Member" },
            capabilities: [],
            is_superuser: false,
            created_at: "2026-08-06T00:00:00Z",
          },
          { status: 201 },
        ),
      ),
    );

    renderWithProviders(<UsersScreen />);

    await user.click(await screen.findByRole("button", { name: "Nový uživatel" }));
    await user.type(screen.getByLabelText("E-mail"), "novy@firma.cz");
    await user.type(screen.getByLabelText("Heslo"), "heslo1234");
    await user.selectOptions(screen.getByLabelText("Role"), "r2");
    await user.click(screen.getByRole("button", { name: "Vytvořit" }));

    expect(screen.queryByLabelText("E-mail")).not.toBeInTheDocument();
  });

  it("surfaces a duplicate email as a 409 on the email field", async () => {
    const user = userEvent.setup();
    server.use(
      ...listing,
      http.post("http://api.test/users", () =>
        HttpResponse.json({ detail: "user already exists" }, { status: 409 }),
      ),
    );

    renderWithProviders(<UsersScreen />);

    await user.click(await screen.findByRole("button", { name: "Nový uživatel" }));
    await user.type(screen.getByLabelText("E-mail"), "dvakrat@firma.cz");
    await user.type(screen.getByLabelText("Heslo"), "heslo1234");
    await user.selectOptions(screen.getByLabelText("Role"), "r2");
    await user.click(screen.getByRole("button", { name: "Vytvořit" }));

    expect(await screen.findByText("Uživatel s tímto e-mailem už existuje.")).toBeInTheDocument();
  });
});
