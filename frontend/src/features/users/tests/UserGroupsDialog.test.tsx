import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { server } from "@/test/msw/server";
import { renderWithProviders } from "@/test/render";
import { UserGroupsDialog } from "@/features/users";

const user = { id: "u1", email: "clen@firma.cz" };

const group = (id: string, name: string) => ({ id, name, created_at: "2026-08-01T00:00:00Z" });

const groupsHandler = http.get("http://api.test/groups", () =>
  HttpResponse.json([group("g1", "Klienti"), group("g2", "Docasna")]),
);

const membershipsHandler = (memberIds: string[]) =>
  http.get("http://api.test/users/u1/groups", () =>
    HttpResponse.json(memberIds.map((id) => group(id, id === "g1" ? "Klienti" : "Docasna"))),
  );

const renderDialog = () =>
  renderWithProviders(
    <UserGroupsDialog
      open
      onOpenChange={() => undefined}
      user={{ ...user, role: { id: "r2", name: "Member" }, is_superuser: false } as never}
    />,
  );

describe("UserGroupsDialog", () => {
  it("lists the groups the user belongs to and removes one", async () => {
    const actor = userEvent.setup();
    let memberships: string[] = ["g1"];
    server.use(
      groupsHandler,
      http.get("http://api.test/users/u1/groups", () =>
        HttpResponse.json(memberships.map((id) => group(id, id === "g1" ? "Klienti" : "Docasna"))),
      ),
      http.delete("http://api.test/groups/g1/members/u1", () => {
        memberships = [];
        return new HttpResponse(null, { status: 204 });
      }),
    );

    renderDialog();

    expect(await screen.findByText("Klienti")).toBeInTheDocument();
    await actor.click(screen.getByRole("button", { name: "Odebrat skupinu Klienti" }));

    expect(
      await screen.findByText("Uživatel zatím není členem žádné skupiny."),
    ).toBeInTheDocument();
  });

  it("adds a group from the select", async () => {
    const actor = userEvent.setup();
    let memberships: string[] = [];
    server.use(
      groupsHandler,
      http.get("http://api.test/users/u1/groups", () =>
        HttpResponse.json(memberships.map((id) => group(id, "Docasna"))),
      ),
      http.post("http://api.test/groups/g2/members", async ({ request }) => {
        expect(await request.json()).toEqual({ user_id: "u1" });
        memberships = ["g2"];
        return new HttpResponse(null, { status: 204 });
      }),
    );

    renderDialog();

    await screen.findByText("Uživatel zatím není členem žádné skupiny.");
    await actor.selectOptions(screen.getByLabelText("Přidat do skupiny"), "g2");

    expect(await screen.findByText("Docasna")).toBeInTheDocument();
  });

  it("offers only the groups the user is not already in", async () => {
    server.use(groupsHandler, membershipsHandler(["g1"]));

    renderDialog();

    expect(await screen.findByText("Klienti")).toBeInTheDocument();
    const options = Array.from(
      screen.getByLabelText<HTMLSelectElement>("Přidat do skupiny").options,
    ).map((option) => option.label);
    expect(options).toEqual(["Vyberte skupinu", "Docasna"]);
  });

  it("reports a load failure instead of a silently empty list", async () => {
    server.use(
      http.get("http://api.test/groups", () => new HttpResponse(null, { status: 500 })),
      membershipsHandler([]),
    );

    renderDialog();

    expect(await screen.findByText("Skupiny se nepodařilo načíst.")).toBeInTheDocument();
  });

  it("fetches nothing while closed, instead of hitting /users//groups", async () => {
    const requested = vi.fn();
    server.use(
      http.get("http://api.test/users//groups", () => {
        requested();
        return HttpResponse.json([]);
      }),
    );

    renderWithProviders(
      <UserGroupsDialog
        open={false}
        onOpenChange={() => undefined}
        user={null}
      />,
    );

    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(requested).not.toHaveBeenCalled();
  });
});
