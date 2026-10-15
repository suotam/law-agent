import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import { Route, Routes } from "react-router";
import { server } from "@/test/msw/server";
import { renderWithProviders } from "@/test/render";
import { RequireCapability } from "@/app/middlewares/RequireCapability";
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

const renderCapabilityGuardedRoutes = () =>
  renderWithProviders(
    <Routes>
      <Route path="/">
        <Route
          index
          element={<p>chat</p>}
        />
        <Route element={<RequireCapability capability="manage_users" />}>
          <Route
            path="users"
            element={<p>admin area</p>}
          />
        </Route>
      </Route>
    </Routes>,
    { route: "/users" },
  );

// Mirrors router.tsx's /admin/groups/:id/access nesting: reaching the group-access
// tool requires BOTH manage_groups and manage_org_files_structure, since granting
// access to others needs the full org tree that only a structure manager can see.
const renderNestedCapabilityGuardedRoutes = () =>
  renderWithProviders(
    <Routes>
      <Route path="/">
        <Route
          index
          element={<p>chat</p>}
        />
        <Route element={<RequireCapability capability="manage_groups" />}>
          <Route
            path="admin/groups"
            element={<p>groups area</p>}
          />
          <Route element={<RequireCapability capability="manage_org_files_structure" />}>
            <Route
              path="admin/groups/:id/access"
              element={<p>group access area</p>}
            />
          </Route>
        </Route>
      </Route>
    </Routes>,
    { route: "/admin/groups/g1/access" },
  );

const renderSuperuserGuardedRoutes = () =>
  renderWithProviders(
    <Routes>
      <Route path="/">
        <Route
          index
          element={<p>chat</p>}
        />
        <Route element={<RequireCapability superuser />}>
          <Route
            path="admin/roles"
            element={<p>roles area</p>}
          />
        </Route>
      </Route>
    </Routes>,
    { route: "/admin/roles" },
  );

describe("RequireCapability", () => {
  afterEach(() => clearToken());

  it("shows neither route while auth is loading", () => {
    setToken("token");
    // eslint-disable-next-line @typescript-eslint/no-empty-function -- never resolves, simulating a pending request
    server.use(http.get("http://api.test/auth/me", () => new Promise(() => {})));

    renderCapabilityGuardedRoutes();

    expect(screen.queryByText("chat")).not.toBeInTheDocument();
    expect(screen.queryByText("admin area")).not.toBeInTheDocument();
  });

  it("redirects a user lacking the capability", async () => {
    setToken("token");
    meResponding([]);

    renderCapabilityGuardedRoutes();

    expect(await screen.findByText("chat")).toBeInTheDocument();
    expect(screen.queryByText("admin area")).not.toBeInTheDocument();
  });

  it("renders the guarded route for a user with the capability", async () => {
    setToken("token");
    meResponding(["manage_users"]);

    renderCapabilityGuardedRoutes();

    expect(await screen.findByText("admin area")).toBeInTheDocument();
  });

  it("renders a capability-guarded route for a superuser without that capability listed", async () => {
    setToken("token");
    meResponding([], true);

    renderCapabilityGuardedRoutes();

    expect(await screen.findByText("admin area")).toBeInTheDocument();
  });

  it("redirects a manage_groups-only user away from a nested route also requiring manage_org_files_structure", async () => {
    setToken("token");
    meResponding(["manage_groups"]);

    renderNestedCapabilityGuardedRoutes();

    expect(await screen.findByText("chat")).toBeInTheDocument();
    expect(screen.queryByText("group access area")).not.toBeInTheDocument();
  });

  it("renders the nested route for a user holding both required capabilities", async () => {
    setToken("token");
    meResponding(["manage_groups", "manage_org_files_structure"]);

    renderNestedCapabilityGuardedRoutes();

    expect(await screen.findByText("group access area")).toBeInTheDocument();
  });

  it("redirects a non-superuser away from a superuser-only route even with every capability", async () => {
    setToken("token");
    meResponding(["manage_users", "manage_groups", "manage_org_files_structure"]);

    renderSuperuserGuardedRoutes();

    expect(await screen.findByText("chat")).toBeInTheDocument();
    expect(screen.queryByText("roles area")).not.toBeInTheDocument();
  });

  it("renders a superuser-only route for a superuser", async () => {
    setToken("token");
    meResponding([], true);

    renderSuperuserGuardedRoutes();

    expect(await screen.findByText("roles area")).toBeInTheDocument();
  });
});
