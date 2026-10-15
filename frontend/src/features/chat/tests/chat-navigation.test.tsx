import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it } from "vitest";
import { AppLayout } from "@/app/layouts/AppLayout";
import { ChatThreadPage } from "@/app/routes/chat.$id";
import { NewChatPage } from "@/app/routes/chat";
import { useSourceScopeStore } from "@/features/sources";
import { server } from "@/test/msw/server";

const conversation = {
  id: "c1",
  title: "",
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

const FRAMES = [
  'data: {"type":"start","messageId":"m1"}\n\n',
  'data: {"type":"text-start","id":"answer"}\n\n',
  'data: {"type":"text-delta","id":"answer","delta":"Ano."}\n\n',
  'data: {"type":"text-end","id":"answer"}\n\n',
  'data: {"type":"finish"}\n\n',
  "data: [DONE]\n\n",
];

/*
 * The answer is held back until the test releases it, which is the situation the bug
 * lives in: the navigation to /chat/:id happens while the turn is still streaming.
 */
const gatedStream = (gate: Promise<void>) => {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    async start(controller) {
      await gate;
      for (const frame of FRAMES) controller.enqueue(encoder.encode(frame));
      controller.close();
    },
  });

  return new HttpResponse(body, {
    headers: {
      "content-type": "text/event-stream",
      "x-vercel-ai-ui-message-stream": "v1",
    },
  });
};

const renderApp = (route = "/") => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route element={<AppLayout />}>
            <Route
              path="/"
              element={<NewChatPage />}
            />
            <Route
              path="/chat/:id"
              element={<ChatThreadPage />}
            />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
};

describe("sending the first message of a new chat", () => {
  beforeEach(() => {
    useSourceScopeStore.getState().reset(["laws"]);
  });

  it("keeps the streaming turn visible across the navigation to the thread", async () => {
    let releaseStream: () => void = () => undefined;
    const streamGate = new Promise<void>((resolve) => {
      releaseStream = resolve;
    });

    server.use(
      http.get("http://api.test/conversations", () => HttpResponse.json([conversation])),
      http.post("http://api.test/conversations", () => HttpResponse.json(conversation)),
      http.get("http://api.test/conversations/c1", () =>
        HttpResponse.json({ ...conversation, scope: ["laws"] }),
      ),
      // Matches the backend: a turn reaches the archive only once its stream completes.
      http.get("http://api.test/conversations/c1/history", () => HttpResponse.json([])),
      http.post("http://api.test/conversations/c1/messages", () => gatedStream(streamGate)),
    );

    const user = userEvent.setup();
    renderApp();

    await user.type(await screen.findByPlaceholderText("Zeptejte se…"), "Je smlouva platná?");
    await user.keyboard("{Enter}");

    // The frozen-scope badge only exists on the thread page, so it marks the navigation
    // as done — while the answer is still on the wire.
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Zobrazit informace o zdrojích" }),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText("Je smlouva platná?")).toBeInTheDocument();
    expect(screen.queryByText("Na co se chcete zeptat?")).not.toBeInTheDocument();

    /*
     * The frames are consumed outside React, so the pipeline needs a macrotask of its own
     * before waitFor's act-wrapped polling can observe anything.
     */
    await act(async () => {
      releaseStream();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(await screen.findByText("Ano.")).toBeInTheDocument();
  });

  it("drops the finished thread when the user starts a new chat", async () => {
    server.use(
      http.get("http://api.test/conversations", () => HttpResponse.json([conversation])),
      http.post("http://api.test/conversations", () => HttpResponse.json(conversation)),
      http.get("http://api.test/conversations/c1", () =>
        HttpResponse.json({ ...conversation, scope: ["laws"] }),
      ),
      http.get("http://api.test/conversations/c1/history", () => HttpResponse.json([])),
      http.post("http://api.test/conversations/c1/messages", () => gatedStream(Promise.resolve())),
    );

    const user = userEvent.setup();
    renderApp();

    await user.type(await screen.findByPlaceholderText("Zeptejte se…"), "Je smlouva platná?");
    await user.keyboard("{Enter}");
    expect(await screen.findByText("Ano.")).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: "Nový chat" }));

    expect(await screen.findByText("Na co se chcete zeptat?")).toBeInTheDocument();
    expect(screen.queryByText("Je smlouva platná?")).not.toBeInTheDocument();
  });

  it("hydrates a stored thread from history when it is opened from the sidebar", async () => {
    server.use(
      http.get("http://api.test/conversations", () =>
        HttpResponse.json([{ ...conversation, title: "Výpovědní lhůta" }]),
      ),
      http.get("http://api.test/conversations/c1", () =>
        HttpResponse.json({ ...conversation, scope: ["laws"] }),
      ),
      http.get("http://api.test/conversations/c1/history", () =>
        HttpResponse.json([
          { id: "u1", role: "user", parts: [{ type: "text", text: "Jak dlouhá je výpověď?" }] },
          { id: "a1", role: "assistant", parts: [{ type: "text", text: "Dva měsíce." }] },
        ]),
      ),
    );

    const user = userEvent.setup();
    renderApp();

    await user.click(await screen.findByRole("link", { name: "Výpovědní lhůta" }));

    expect(await screen.findByText("Jak dlouhá je výpověď?")).toBeInTheDocument();
    expect(screen.getByText("Dva měsíce.")).toBeInTheDocument();
  });
});

describe("an existing thread", () => {
  beforeEach(() => {
    // What a reload leaves behind: the picker is in-memory only and starts empty.
    useSourceScopeStore.getState().reset([]);
  });

  it("still sends after a reload, when the scope picker is empty", async () => {
    const sentBodies: unknown[] = [];

    server.use(
      http.get("http://api.test/conversations", () => HttpResponse.json([conversation])),
      http.get("http://api.test/conversations/c1", () =>
        HttpResponse.json({ ...conversation, scope: ["laws"] }),
      ),
      http.get("http://api.test/conversations/c1/history", () => HttpResponse.json([])),
      http.post("http://api.test/conversations/c1/messages", async ({ request }) => {
        sentBodies.push(await request.json());
        return gatedStream(Promise.resolve());
      }),
    );

    const user = userEvent.setup();
    renderApp("/chat/c1");

    const composer = await screen.findByPlaceholderText("Zeptejte se…");
    // The thread's scope is frozen server-side, so the rule has nothing left to warn about.
    expect(screen.queryByText(/Vyberte zdroje/)).not.toBeInTheDocument();

    await user.type(composer, "A co odstupné?");
    await user.keyboard("{Enter}");

    await waitFor(() => expect(sentBodies).toHaveLength(1));
    expect(sentBodies[0]).toEqual({ question: "A co odstupné?", attachment_ids: [] });
  });

  it("refetches its history after a turn, so leaving and returning keeps the answer", async () => {
    // The backend archives the turn only once the stream ends; the cached history predates it.
    let archive: unknown[] = [];

    server.use(
      http.get("http://api.test/conversations", () =>
        HttpResponse.json([
          { ...conversation, title: "Výpovědní lhůta" },
          { ...conversation, id: "c2", title: "Konkurenční doložka" },
        ]),
      ),
      http.get("http://api.test/conversations/:id", ({ params }) =>
        HttpResponse.json({ ...conversation, id: params.id, scope: ["laws"] }),
      ),
      http.get("http://api.test/conversations/c1/history", () => HttpResponse.json(archive)),
      http.get("http://api.test/conversations/c2/history", () => HttpResponse.json([])),
      http.post("http://api.test/conversations/c1/messages", () => {
        archive = [
          { id: "u1", role: "user", parts: [{ type: "text", text: "A co odstupné?" }] },
          { id: "a1", role: "assistant", parts: [{ type: "text", text: "Ano." }] },
        ];
        return gatedStream(Promise.resolve());
      }),
    );

    const user = userEvent.setup();
    renderApp("/chat/c1");

    await user.type(await screen.findByPlaceholderText("Zeptejte se…"), "A co odstupné?");
    await user.keyboard("{Enter}");
    expect(await screen.findByText("Ano.")).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: "Konkurenční doložka" }));
    await waitFor(() => expect(screen.queryByText("Ano.")).not.toBeInTheDocument());

    await user.click(screen.getByRole("link", { name: "Výpovědní lhůta" }));

    expect(await screen.findByText("A co odstupné?")).toBeInTheDocument();
    expect(screen.getByText("Ano.")).toBeInTheDocument();
  });
});
