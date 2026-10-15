import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "@/test/msw/server";
import { renderWithProviders } from "@/test/render";
import { getToken, LoginForm } from "@/features/auth";

describe("LoginForm", () => {
  it("rejects a malformed email client-side and never calls the API", async () => {
    const user = userEvent.setup();
    renderWithProviders(<LoginForm />);

    await user.type(screen.getByLabelText("E-mail"), "not-an-email");
    await user.type(screen.getByLabelText("Heslo"), "secret123");
    await user.click(screen.getByRole("button", { name: "Přihlásit se" }));

    expect(await screen.findByText("Zadejte platnou e-mailovou adresu.")).toBeInTheDocument();
  });

  it("stores the token returned by a successful login", async () => {
    const user = userEvent.setup();
    server.use(
      http.post("http://api.test/auth/login", () =>
        HttpResponse.json({ access_token: "token-123", token_type: "bearer" }),
      ),
      http.get("http://api.test/auth/me", () =>
        HttpResponse.json({
          id: "u1",
          email: "jan@fir.cz",
          role: "member",
          created_at: "2026-08-01T00:00:00Z",
        }),
      ),
    );
    renderWithProviders(<LoginForm />);

    await user.type(screen.getByLabelText("E-mail"), "jan@fir.cz");
    await user.type(screen.getByLabelText("Heslo"), "secret123");
    await user.click(screen.getByRole("button", { name: "Přihlásit se" }));

    await waitFor(() => expect(getToken()).toBe("token-123"));
  });

  it("shows one message for a 401, whatever the cause", async () => {
    const user = userEvent.setup();
    server.use(
      http.post("http://api.test/auth/login", () =>
        HttpResponse.json({ detail: "invalid email or password" }, { status: 401 }),
      ),
    );
    renderWithProviders(<LoginForm />);

    await user.type(screen.getByLabelText("E-mail"), "jan@fir.cz");
    await user.type(screen.getByLabelText("Heslo"), "wrong");
    await user.click(screen.getByRole("button", { name: "Přihlásit se" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Nesprávný e-mail nebo heslo.");
  });
});
