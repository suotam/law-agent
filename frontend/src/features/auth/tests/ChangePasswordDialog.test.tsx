import { useState } from "react";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import { server } from "@/test/msw/server";
import { renderWithProviders } from "@/test/render";
import { ChangePasswordDialog } from "@/features/auth";

const DialogHarness = () => {
  const [open, setOpen] = useState(true);
  return (
    <ChangePasswordDialog
      open={open}
      onOpenChange={setOpen}
    />
  );
};

describe("ChangePasswordDialog", () => {
  afterEach(() => server.resetHandlers());

  it("changes the password and closes the dialog", async () => {
    const user = userEvent.setup();
    let sent: unknown;
    server.use(
      http.post("http://api.test/me/password", async ({ request }) => {
        sent = await request.json();
        return new HttpResponse(null, { status: 204 });
      }),
    );

    renderWithProviders(<DialogHarness />);

    await user.type(screen.getByLabelText("Aktuální heslo"), "stare-heslo");
    await user.type(screen.getByLabelText("Nové heslo"), "nove-heslo-123");
    await user.click(screen.getByRole("button", { name: "Změnit heslo" }));

    expect(sent).toEqual({ current_password: "stare-heslo", new_password: "nove-heslo-123" });
    expect(screen.queryByLabelText("Aktuální heslo")).not.toBeInTheDocument();
  });

  it("reports a wrong current password inline and changes nothing", async () => {
    const user = userEvent.setup();
    server.use(
      http.post("http://api.test/me/password", () =>
        HttpResponse.json({ detail: "current password is incorrect" }, { status: 403 }),
      ),
    );

    renderWithProviders(<DialogHarness />);

    await user.type(screen.getByLabelText("Aktuální heslo"), "spatne");
    await user.type(screen.getByLabelText("Nové heslo"), "nove-heslo-123");
    await user.click(screen.getByRole("button", { name: "Změnit heslo" }));

    expect(await screen.findByText("Aktuální heslo je nesprávné.")).toBeInTheDocument();
    // The dialog stays open: the change did not happen.
    expect(screen.getByLabelText("Aktuální heslo")).toBeInTheDocument();
  });
});
