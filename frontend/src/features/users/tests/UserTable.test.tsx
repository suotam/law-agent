import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import { useLocation } from "react-router";
import { server } from "@/test/msw/server";
import { renderWithProviders } from "@/test/render";
import { clearToken, setToken } from "@/features/auth";
import { UserTable } from "@/features/users";

const LocationProbe = () => {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
};

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

const baseUser = {
  id: "u1",
  email: "kolega@firma.cz",
  role: { id: "r2", name: "Member" },
  capabilities: [],
  is_superuser: false,
  is_active: true,
  created_at: "2026-08-05T00:00:00Z",
};

const adminUser = {
  ...baseUser,
  id: "u2",
  email: "vedouci@firma.cz",
  role: { id: "r1", name: "Admin" },
  is_superuser: true,
};

const superuserCaller = {
  id: "u0",
  email: "ja@firma.cz",
  role: { id: "r1", name: "Admin" },
  capabilities: [],
  is_superuser: true,
  is_active: true,
  created_at: "2026-08-01T00:00:00Z",
};

const managerCaller = {
  ...superuserCaller,
  role: { id: "r2", name: "Manager" },
  capabilities: ["manage_users"],
  is_superuser: false,
};

const groupManagerCaller = {
  ...superuserCaller,
  role: { id: "r2", name: "Spravce skupin" },
  capabilities: ["manage_users", "manage_groups"],
  is_superuser: false,
};

// The first matching MSW handler wins, so the list/roles handlers below must
// be registered before any per-test override that re-points the same route.
const rolesHandler = http.get("http://api.test/roles", () => HttpResponse.json(roles));
const usersHandler = (body: () => object[]) =>
  http.get("http://api.test/users", () => HttpResponse.json(body()));
const meHandler = (user: object) =>
  http.get("http://api.test/auth/me", () => HttpResponse.json(user));

const superuserSetup = [rolesHandler, usersHandler(() => [baseUser]), meHandler(superuserCaller)];

const openRowMenu = async (user: ReturnType<typeof userEvent.setup>, email: string) => {
  await user.click(await screen.findByRole("button", { name: `Akce uživatele ${email}` }));
};

describe("UserTable", () => {
  afterEach(() => clearToken());

  it("renders users with their role selects", async () => {
    setToken("token");
    server.use(...superuserSetup);

    renderWithProviders(<UserTable />);

    expect(await screen.findByText("kolega@firma.cz")).toBeInTheDocument();
    const select = screen.getByRole("combobox", { name: "Role uživatele kolega@firma.cz" });
    expect(select).toHaveValue("r2");
  });

  it("changes a user's role and reflects it after refetch", async () => {
    setToken("token");
    const user = userEvent.setup();
    let currentUser = baseUser;
    server.use(
      rolesHandler,
      usersHandler(() => [currentUser]),
      meHandler(superuserCaller),
      http.patch("http://api.test/users/u1", () => {
        currentUser = { ...currentUser, role: { id: "r1", name: "Admin" } };
        return HttpResponse.json(currentUser);
      }),
    );

    renderWithProviders(<UserTable />);

    const select = await screen.findByRole("combobox", { name: "Role uživatele kolega@firma.cz" });
    await user.selectOptions(select, "r1");

    expect(await screen.findByDisplayValue("Admin")).toBeInTheDocument();
  });

  it("shows the newly picked role immediately, without flickering back to the old one while the PATCH is in flight", async () => {
    setToken("token");
    const user = userEvent.setup();
    let resolvePatch: () => void = () => undefined;
    server.use(
      rolesHandler,
      usersHandler(() => [baseUser]),
      meHandler(superuserCaller),
      http.patch("http://api.test/users/u1", async () => {
        await new Promise<void>((resolve) => {
          resolvePatch = resolve;
        });
        return HttpResponse.json({ ...baseUser, role: { id: "r1", name: "Admin" } });
      }),
    );

    renderWithProviders(<UserTable />);

    const select = await screen.findByRole("combobox", { name: "Role uživatele kolega@firma.cz" });
    await user.selectOptions(select, "r1");

    // The PATCH above is still pending (its promise hasn't been resolved yet),
    // so this checks the optimistic update, not the server's response.
    expect(select).toHaveValue("r1");

    resolvePatch();
  });

  it("offers no role change on the caller's own row", async () => {
    setToken("token");
    server.use(
      rolesHandler,
      usersHandler(() => [baseUser]),
      meHandler({ ...superuserCaller, id: "u1" }),
    );

    renderWithProviders(<UserTable />);

    const select = await screen.findByRole("combobox", { name: "Role uživatele kolega@firma.cz" });
    expect(select).toBeDisabled();
  });

  it("opens the own-password change dialog from the own row's menu", async () => {
    setToken("token");
    const user = userEvent.setup();
    let sent: unknown;
    server.use(
      rolesHandler,
      usersHandler(() => [baseUser]),
      meHandler({ ...superuserCaller, id: "u1" }),
      http.post("http://api.test/me/password", async ({ request }) => {
        sent = await request.json();
        return new HttpResponse(null, { status: 204 });
      }),
    );

    renderWithProviders(<UserTable />);

    await openRowMenu(user, "kolega@firma.cz");
    expect(screen.queryByRole("menuitem", { name: "Deaktivovat" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("menuitem", { name: "Změnit heslo" }));

    await user.type(screen.getByLabelText("Aktuální heslo"), "stare-heslo");
    await user.type(screen.getByLabelText("Nové heslo"), "nove-heslo-123");
    await user.click(screen.getByRole("button", { name: "Změnit heslo" }));

    expect(sent).toEqual({ current_password: "stare-heslo", new_password: "nove-heslo-123" });
  });

  it("navigates to the user's access page from the row menu, for a superuser", async () => {
    setToken("token");
    const user = userEvent.setup();
    server.use(
      rolesHandler,
      usersHandler(() => [baseUser]),
      meHandler(superuserCaller),
    );

    renderWithProviders(
      <>
        <UserTable />
        <LocationProbe />
      </>,
    );

    await openRowMenu(user, "kolega@firma.cz");
    await user.click(screen.getByRole("menuitem", { name: "Přístup k souborům" }));

    expect(screen.getByTestId("location")).toHaveTextContent("/admin/users/u1/access");
  });

  it("hides the access menu item from a manager who lacks manage_org_files_structure", async () => {
    setToken("token");
    const user = userEvent.setup();
    server.use(
      rolesHandler,
      usersHandler(() => [baseUser]),
      meHandler(managerCaller),
    );

    renderWithProviders(<UserTable />);

    await openRowMenu(user, "kolega@firma.cz");
    expect(screen.queryByRole("menuitem", { name: "Přístup k souborům" })).not.toBeInTheDocument();
  });

  it("shows the access menu item to a manager who also holds manage_org_files_structure", async () => {
    setToken("token");
    const user = userEvent.setup();
    server.use(
      rolesHandler,
      usersHandler(() => [baseUser]),
      meHandler({ ...managerCaller, capabilities: ["manage_users", "manage_org_files_structure"] }),
    );

    renderWithProviders(<UserTable />);

    await openRowMenu(user, "kolega@firma.cz");
    expect(screen.getByRole("menuitem", { name: "Přístup k souborům" })).toBeInTheDocument();
  });

  it("does not offer the superuser role to a caller who is not a superuser", async () => {
    setToken("token");
    server.use(
      rolesHandler,
      usersHandler(() => [baseUser]),
      meHandler(managerCaller),
    );

    renderWithProviders(<UserTable />);

    const select = await screen.findByRole("combobox", { name: "Role uživatele kolega@firma.cz" });
    const options = Array.from((select as HTMLSelectElement).options).map((option) => option.label);
    expect(options).toEqual(["Member"]);
  });

  it("lets a manager do nothing to a superuser's account", async () => {
    setToken("token");
    server.use(
      rolesHandler,
      usersHandler(() => [adminUser]),
      meHandler(managerCaller),
    );

    renderWithProviders(<UserTable />);

    const select = await screen.findByRole("combobox", { name: "Role uživatele vedouci@firma.cz" });
    expect(select).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: "Akce uživatele vedouci@firma.cz" }),
    ).not.toBeInTheDocument();
  });

  it("hides the row menu from a different superuser viewing a superuser's row", async () => {
    setToken("token");
    server.use(
      rolesHandler,
      usersHandler(() => [adminUser]),
      meHandler(superuserCaller),
    );

    renderWithProviders(<UserTable />);

    await screen.findByText("vedouci@firma.cz");
    expect(
      screen.queryByRole("button", { name: "Akce uživatele vedouci@firma.cz" }),
    ).not.toBeInTheDocument();
  });

  it("shows only change-password, no access item, in a superuser's own row menu", async () => {
    setToken("token");
    const user = userEvent.setup();
    server.use(
      rolesHandler,
      usersHandler(() => [adminUser]),
      meHandler(adminUser),
    );

    renderWithProviders(<UserTable />);

    await openRowMenu(user, "vedouci@firma.cz");
    expect(screen.getByRole("menuitem", { name: "Změnit heslo" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Přístup k souborům" })).not.toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Deaktivovat" })).not.toBeInTheDocument();
  });

  it("shows a superuser's real role to a manager, even though it's not an option a manager can pick", async () => {
    setToken("token");
    server.use(
      rolesHandler,
      usersHandler(() => [adminUser]),
      meHandler(managerCaller),
    );

    renderWithProviders(<UserTable />);

    const select = await screen.findByRole("combobox", { name: "Role uživatele vedouci@firma.cz" });
    expect(select).toHaveValue("r1");
    expect(screen.getByDisplayValue("Admin")).toBeInTheDocument();
  });

  it("deactivates a user from the row menu and shows the account as deactivated", async () => {
    setToken("token");
    const user = userEvent.setup();
    let currentUser = baseUser;
    server.use(
      rolesHandler,
      usersHandler(() => [currentUser]),
      meHandler(superuserCaller),
      http.delete("http://api.test/users/u1", () => {
        currentUser = { ...currentUser, is_active: false };
        return new HttpResponse(null, { status: 204 });
      }),
    );

    renderWithProviders(<UserTable />);

    await openRowMenu(user, "kolega@firma.cz");
    await user.click(screen.getByRole("menuitem", { name: "Deaktivovat" }));

    expect(await screen.findByText("Deaktivovaný")).toBeInTheDocument();
    // A deactivated account is not a role-assignment target; undo is
    // reactivation, not another role edit.
    expect(
      screen.queryByRole("combobox", { name: "Role uživatele kolega@firma.cz" }),
    ).not.toBeInTheDocument();

    await openRowMenu(user, "kolega@firma.cz");
    expect(screen.getByRole("menuitem", { name: "Reaktivovat" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Deaktivovat" })).not.toBeInTheDocument();
  });

  it("reactivates a deactivated user from the row menu", async () => {
    setToken("token");
    const user = userEvent.setup();
    let currentUser = { ...baseUser, is_active: false };
    server.use(
      rolesHandler,
      usersHandler(() => [currentUser]),
      meHandler(superuserCaller),
      http.post("http://api.test/users/u1/activate", () => {
        currentUser = baseUser;
        return HttpResponse.json(baseUser);
      }),
    );

    renderWithProviders(<UserTable />);

    await openRowMenu(user, "kolega@firma.cz");
    await user.click(screen.getByRole("menuitem", { name: "Reaktivovat" }));

    expect(
      await screen.findByRole("combobox", { name: "Role uživatele kolega@firma.cz" }),
    ).toHaveValue("r2");
    expect(screen.queryByText("Deaktivovaný")).not.toBeInTheDocument();
    expect(currentUser).toEqual(baseUser);
  });

  it("resets a user's password from the row menu", async () => {
    setToken("token");
    const user = userEvent.setup();
    let resetWith: { new_password?: string } = {};
    server.use(
      rolesHandler,
      usersHandler(() => [baseUser]),
      meHandler(superuserCaller),
      http.put("http://api.test/users/u1/password", async ({ request }) => {
        resetWith = (await request.json()) as { new_password: string };
        return new HttpResponse(null, { status: 204 });
      }),
    );

    renderWithProviders(<UserTable />);

    await openRowMenu(user, "kolega@firma.cz");
    await user.click(screen.getByRole("menuitem", { name: "Resetovat heslo" }));

    await user.type(screen.getByLabelText("Nové heslo"), "nove-heslo-123");
    await user.click(screen.getByRole("button", { name: "Resetovat" }));

    expect(resetWith).toEqual({ new_password: "nove-heslo-123" });
    expect(screen.queryByLabelText("Nové heslo")).not.toBeInTheDocument();
  });

  it("shows the groups menu item to a caller holding both manage_users and manage_groups", async () => {
    setToken("token");
    const user = userEvent.setup();
    server.use(
      rolesHandler,
      usersHandler(() => [baseUser]),
      meHandler(groupManagerCaller),
    );

    renderWithProviders(<UserTable />);

    await openRowMenu(user, "kolega@firma.cz");
    expect(screen.getByRole("menuitem", { name: "Skupiny" })).toBeInTheDocument();
  });

  it("opens the user's groups dialog from the row menu", async () => {
    setToken("token");
    const user = userEvent.setup();
    server.use(
      rolesHandler,
      usersHandler(() => [baseUser]),
      meHandler(groupManagerCaller),
      http.get("http://api.test/groups", () =>
        HttpResponse.json([{ id: "g1", name: "Klienti", created_at: "2026-08-01T00:00:00Z" }]),
      ),
      http.get("http://api.test/users/u1/groups", () => HttpResponse.json([])),
    );

    renderWithProviders(<UserTable />);

    await openRowMenu(user, "kolega@firma.cz");
    await user.click(screen.getByRole("menuitem", { name: "Skupiny" }));

    expect(
      await screen.findByRole("dialog", { name: "Skupiny uživatele kolega@firma.cz" }),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("Uživatel zatím není členem žádné skupiny."),
    ).toBeInTheDocument();
  });

  it("hides the groups menu item from a caller who only manages users", async () => {
    setToken("token");
    const user = userEvent.setup();
    server.use(
      rolesHandler,
      usersHandler(() => [baseUser]),
      meHandler(managerCaller),
    );

    renderWithProviders(<UserTable />);

    await openRowMenu(user, "kolega@firma.cz");
    expect(screen.queryByRole("menuitem", { name: "Skupiny" })).not.toBeInTheDocument();
  });

  it("hides the groups menu item on the caller's own row", async () => {
    setToken("token");
    const user = userEvent.setup();
    server.use(
      rolesHandler,
      usersHandler(() => [baseUser]),
      meHandler({ ...groupManagerCaller, id: "u1" }),
    );

    renderWithProviders(<UserTable />);

    await openRowMenu(user, "kolega@firma.cz");
    expect(screen.queryByRole("menuitem", { name: "Skupiny" })).not.toBeInTheDocument();
  });

  it("hides the groups menu item from a caller who only manages groups", async () => {
    setToken("token");
    const user = userEvent.setup();
    server.use(
      rolesHandler,
      usersHandler(() => [baseUser]),
      meHandler({ ...groupManagerCaller, capabilities: ["manage_groups"] }),
    );

    renderWithProviders(<UserTable />);

    await openRowMenu(user, "kolega@firma.cz");
    expect(screen.queryByRole("menuitem", { name: "Skupiny" })).not.toBeInTheDocument();
  });
});
