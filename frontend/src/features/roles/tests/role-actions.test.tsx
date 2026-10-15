import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { server } from "@/test/msw/server";
import { renderWithProviders } from "@/test/render";
import { RolesScreen } from "@/features/roles";

const existingRole = {
  id: "r2",
  name: "Files Manager",
  is_superuser: false,
  capabilities: ["manage_org_files_structure"],
  created_at: "2026-08-02T00:00:00Z",
};

const listing = [http.get("http://api.test/roles", () => HttpResponse.json([existingRole]))];

describe("RoleDialog", () => {
  it("creates a role with just a name", async () => {
    const user = userEvent.setup();
    server.use(
      ...listing,
      http.post("http://api.test/roles", () =>
        HttpResponse.json(
          {
            id: "r3",
            name: "Support",
            is_superuser: false,
            capabilities: [],
            created_at: "2026-08-07T00:00:00Z",
          },
          { status: 201 },
        ),
      ),
    );

    renderWithProviders(<RolesScreen />);

    await user.click(await screen.findByRole("button", { name: "Nová role" }));
    await user.type(screen.getByLabelText("Název role"), "Support");
    await user.click(screen.getByRole("button", { name: "Vytvořit" }));

    expect(screen.queryByLabelText("Název role")).not.toBeInTheDocument();
  });

  it("does not persist a capability toggle until Save is clicked", async () => {
    const user = userEvent.setup();
    const putBody = vi.fn();
    server.use(
      ...listing,
      http.patch("http://api.test/roles/r2", () => HttpResponse.json(existingRole)),
      http.put("http://api.test/roles/r2/capabilities", async ({ request }) => {
        putBody(await request.json());
        return HttpResponse.json({
          ...existingRole,
          capabilities: ["manage_org_files_structure", "manage_users"],
        });
      }),
    );

    renderWithProviders(<RolesScreen />);

    await user.click(await screen.findByRole("button", { name: "Upravit roli Files Manager" }));
    await user.click(screen.getByLabelText("Správa uživatelů"));

    // Checking the box alone must not call the API -- only Save should.
    expect(putBody).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Uložit" }));

    await waitFor(() =>
      expect(putBody).toHaveBeenCalledWith({
        capabilities: ["manage_org_files_structure", "manage_users"],
      }),
    );
  });

  it("discards a capability toggle when Cancel is clicked instead of Save", async () => {
    const user = userEvent.setup();
    const putBody = vi.fn();
    server.use(
      ...listing,
      http.put("http://api.test/roles/r2/capabilities", async ({ request }) => {
        putBody(await request.json());
        return HttpResponse.json(existingRole);
      }),
    );

    renderWithProviders(<RolesScreen />);

    await user.click(await screen.findByRole("button", { name: "Upravit roli Files Manager" }));
    await user.click(screen.getByLabelText("Správa uživatelů"));
    await user.click(screen.getByRole("button", { name: "Zrušit" }));

    expect(putBody).not.toHaveBeenCalled();

    // Reopening must show the untouched, still-persisted state, not the
    // discarded local edit from before Cancel.
    await user.click(await screen.findByRole("button", { name: "Upravit roli Files Manager" }));
    expect(screen.getByLabelText("Správa uživatelů")).not.toBeChecked();
  });

  it("re-initializes the staged capabilities each time the dialog is reopened for a role", async () => {
    const user = userEvent.setup();
    let currentCapabilities = existingRole.capabilities;
    server.use(
      http.get("http://api.test/roles", () =>
        HttpResponse.json([{ ...existingRole, capabilities: currentCapabilities }]),
      ),
      http.patch("http://api.test/roles/r2", () => HttpResponse.json(existingRole)),
      http.put("http://api.test/roles/r2/capabilities", async ({ request }) => {
        const body = (await request.json()) as { capabilities: string[] };
        currentCapabilities = body.capabilities;
        return HttpResponse.json({ ...existingRole, capabilities: currentCapabilities });
      }),
    );

    renderWithProviders(<RolesScreen />);

    await user.click(await screen.findByRole("button", { name: "Upravit roli Files Manager" }));
    await user.click(screen.getByLabelText("Správa uživatelů"));
    await user.click(screen.getByRole("button", { name: "Uložit" }));

    // The list refetch after Save must be reflected the next time the
    // dialog opens for this role, not a stale open-time snapshot.
    await user.click(await screen.findByRole("button", { name: "Upravit roli Files Manager" }));
    await waitFor(() => expect(screen.getByLabelText("Správa uživatelů")).toBeChecked());
  });
});
