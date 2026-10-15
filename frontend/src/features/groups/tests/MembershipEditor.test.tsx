import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { server } from "@/test/msw/server";
import { renderWithProviders } from "@/test/render";
import { MembershipEditor } from "@/features/groups";

const group = { id: "g1", name: "Klienti", created_at: "2026-09-05T00:00:00Z" };

const baseUser = (id: string, email: string) => ({
  id,
  email,
  role: { id: "r2", name: "Member" },
  capabilities: [],
  is_superuser: false,
  created_at: "2026-08-05T00:00:00Z",
});

describe("MembershipEditor", () => {
  it("lists current members and removes one", async () => {
    const user = userEvent.setup();
    let members = [baseUser("u1", "clen@firma.cz")];
    server.use(
      http.get("http://api.test/groups/g1/members", () => HttpResponse.json(members)),
      http.get("http://api.test/users", () =>
        HttpResponse.json([baseUser("u1", "clen@firma.cz"), baseUser("u2", "novy@firma.cz")]),
      ),
      http.delete("http://api.test/groups/g1/members/u1", () => {
        members = [];
        return new HttpResponse(null, { status: 204 });
      }),
    );

    renderWithProviders(
      <MembershipEditor
        open
        onOpenChange={() => undefined}
        group={group}
      />,
    );

    expect(await screen.findByText("clen@firma.cz")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Odebrat uživatele clen@firma.cz" }));

    expect(await screen.findByText("Skupina zatím nemá žádné členy.")).toBeInTheDocument();
  });

  it("adds a member from the select", async () => {
    const user = userEvent.setup();
    let members: ReturnType<typeof baseUser>[] = [];
    server.use(
      http.get("http://api.test/groups/g1/members", () => HttpResponse.json(members)),
      http.get("http://api.test/users", () => HttpResponse.json([baseUser("u2", "novy@firma.cz")])),
      http.post("http://api.test/groups/g1/members", () => {
        members = [baseUser("u2", "novy@firma.cz")];
        return new HttpResponse(null, { status: 204 });
      }),
    );

    renderWithProviders(
      <MembershipEditor
        open
        onOpenChange={() => undefined}
        group={group}
      />,
    );

    await screen.findByText("Skupina zatím nemá žádné členy.");
    await user.selectOptions(screen.getByLabelText("Přidat člena"), "u2");

    expect(await screen.findByText("novy@firma.cz")).toBeInTheDocument();
  });

  it("fetches nothing when no group is selected, instead of hitting /groups//members", async () => {
    const requested = vi.fn();
    server.use(
      // The literal malformed path a missing groupId used to produce --
      // ":groupId/members" would not even match an empty segment, so this
      // has to be the exact string to actually catch the regression.
      http.get("http://api.test/groups//members", () => {
        requested();
        return HttpResponse.json([]);
      }),
      http.get("http://api.test/users", () => HttpResponse.json([])),
    );

    renderWithProviders(
      <MembershipEditor
        open={false}
        onOpenChange={() => undefined}
        group={null}
      />,
    );

    // No visible marker to wait on (the component renders nothing for a
    // null group) -- give a wrongly-enabled query a moment to have fired.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(requested).not.toHaveBeenCalled();
  });
});
