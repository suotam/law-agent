import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "@/test/msw/server";
import { renderWithProviders } from "@/test/render";
import { GroupsScreen } from "@/features/groups";

describe("GroupsScreen actions", () => {
  it("creates a group and closes the dialog", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("http://api.test/groups", () => HttpResponse.json([])),
      http.post("http://api.test/groups", () =>
        HttpResponse.json(
          { id: "g1", name: "Klienti", created_at: "2026-09-05T00:00:00Z" },
          { status: 201 },
        ),
      ),
    );

    renderWithProviders(<GroupsScreen />);

    await user.click(await screen.findByRole("button", { name: "Nová skupina" }));
    await user.type(screen.getByLabelText("Název skupiny"), "Klienti");
    await user.click(screen.getByRole("button", { name: "Vytvořit" }));

    expect(screen.queryByLabelText("Název skupiny")).not.toBeInTheDocument();
  });

  it("deletes a group after confirmation", async () => {
    const user = userEvent.setup();
    let deleted = false;
    server.use(
      http.get("http://api.test/groups", () =>
        HttpResponse.json(
          deleted ? [] : [{ id: "g1", name: "Docasna", created_at: "2026-09-05T00:00:00Z" }],
        ),
      ),
      http.delete("http://api.test/groups/g1", () => {
        deleted = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );

    renderWithProviders(<GroupsScreen />);

    await user.click(await screen.findByRole("button", { name: "Smazat skupinu Docasna" }));
    await user.click(screen.getByRole("button", { name: "Smazat" }));

    expect(screen.queryByText("Docasna")).not.toBeInTheDocument();
  });
});
