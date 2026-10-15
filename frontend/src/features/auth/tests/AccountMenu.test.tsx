import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import { server } from "@/test/msw/server";
import { renderWithProviders } from "@/test/render";
import { AccountMenu } from "@/features/auth";
import { clearToken, setToken } from "@/features/auth";

const meResponding = (capabilities: string[], isSuperuser = false) =>
  server.use(
    http.get("http://api.test/auth/me", () =>
      HttpResponse.json({
        id: "u1",
        email: "user@example.com",
        role: { id: "r1", name: "Member" },
        capabilities,
        is_superuser: isSuperuser,
        created_at: "2026-08-01T00:00:00Z",
      }),
    ),
  );

describe("AccountMenu", () => {
  afterEach(() => clearToken());

  it("shows the org files link for a plain member with no capabilities", async () => {
    const user = userEvent.setup();
    setToken("token");
    meResponding([]);

    renderWithProviders(<AccountMenu />);
    await user.click(await screen.findByRole("button", { name: "Účet" }));

    // Every action inside the file browser is permission-gated per node, so any
    // authenticated user gets the entry point even with zero grants.
    expect(await screen.findByRole("link", { name: /Správa dokumentů/ })).toBeInTheDocument();
  });

  it("shows the org files link for a user with the capability", async () => {
    const user = userEvent.setup();
    setToken("token");
    meResponding(["manage_org_files_structure"]);

    renderWithProviders(<AccountMenu />);
    await user.click(await screen.findByRole("button", { name: "Účet" }));

    expect(await screen.findByRole("link", { name: /Správa dokumentů/ })).toBeInTheDocument();
  });

  it("shows the org files link for a superuser regardless of listed capabilities", async () => {
    const user = userEvent.setup();
    setToken("token");
    meResponding([], true);

    renderWithProviders(<AccountMenu />);
    await user.click(await screen.findByRole("button", { name: "Účet" }));

    expect(await screen.findByRole("link", { name: /Správa dokumentů/ })).toBeInTheDocument();
  });
});
