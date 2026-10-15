import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { server } from "@/test/msw/server";
import { renderWithProviders } from "@/test/render";
import { ConversationList } from "@/features/conversations";

const conversation = (id: string, title: string) => ({
  id,
  title,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
});

describe("ConversationList", () => {
  it("renders threads and falls back to a placeholder for an empty title", async () => {
    server.use(
      http.get("http://api.test/conversations", () =>
        HttpResponse.json([conversation("c1", "Výpověď z nájmu"), conversation("c2", "")]),
      ),
    );

    renderWithProviders(<ConversationList />);

    expect(await screen.findByRole("link", { name: "Výpověď z nájmu" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Bez názvu" })).toBeInTheDocument();
  });

  it("shows the cap notice once the list is full", async () => {
    server.use(
      http.get("http://api.test/conversations", () =>
        HttpResponse.json(
          Array.from({ length: 50 }, (_, index) => conversation(`c${index}`, `Vlákno ${index}`)),
        ),
      ),
    );

    renderWithProviders(<ConversationList />);

    expect(await screen.findByText("Zobrazeno posledních 50 konverzací")).toBeInTheDocument();
  });

  it("deletes a thread after confirmation", async () => {
    const user = userEvent.setup();
    const onDelete = vi.fn();
    server.use(
      http.get("http://api.test/conversations", () =>
        HttpResponse.json([conversation("c1", "Výpověď z nájmu")]),
      ),
      http.delete("http://api.test/conversations/c1", () => {
        onDelete();
        return new HttpResponse(null, { status: 204 });
      }),
    );

    renderWithProviders(<ConversationList />);

    await user.click(await screen.findByRole("button", { name: "Smazat konverzaci" }));
    await user.click(await screen.findByRole("button", { name: "Smazat" }));

    await waitFor(() => expect(onDelete).toHaveBeenCalledTimes(1));
  });
});
