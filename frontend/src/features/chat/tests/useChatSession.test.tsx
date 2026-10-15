import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it } from "vitest";
import { server } from "@/test/msw/server";
import { useChatSession } from "@/features/chat";
import { useConversations } from "@/features/conversations";
import { useSourceScopeStore } from "@/features/sources";

const noop = () => undefined;

const wrapper = ({ children }: { children: ReactNode }) => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );
};

const createdConversation = {
  id: "c1",
  title: "",
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

const streamBody = () =>
  new HttpResponse(
    [
      'data: {"type":"start","messageId":"m1"}\n\n',
      'data: {"type":"text-start","id":"answer"}\n\n',
      'data: {"type":"text-delta","id":"answer","delta":"Ano."}\n\n',
      'data: {"type":"text-end","id":"answer"}\n\n',
      'data: {"type":"finish"}\n\n',
      "data: [DONE]\n\n",
    ].join(""),
    {
      headers: {
        "content-type": "text/event-stream",
        "x-vercel-ai-ui-message-stream": "v1",
      },
    },
  );

describe("useChatSession", () => {
  beforeEach(() => {
    useSourceScopeStore.getState().reset(["laws"]);
  });

  it("queues a message typed during an upload and sends it with the attachment id", async () => {
    let releaseUpload: () => void = () => undefined;
    const uploadGate = new Promise<void>((resolve) => {
      releaseUpload = resolve;
    });
    const sentBodies: unknown[] = [];

    server.use(
      http.post("http://api.test/conversations", () => HttpResponse.json(createdConversation)),
      http.get("http://api.test/conversations", () => HttpResponse.json([createdConversation])),
      http.post("http://api.test/attachments", async () => {
        await uploadGate;
        return HttpResponse.json(
          {
            id: "a-1",
            filename: "smlouva.pdf",
            mime: "application/pdf",
            byte_size: 7,
            status: "indexed",
          },
          { status: 201 },
        );
      }),
      http.post("http://api.test/conversations/c1/messages", async ({ request }) => {
        sentBodies.push(await request.json());
        return streamBody();
      }),
    );

    const { result } = renderHook(
      () =>
        useChatSession({ sessionKey: "new-1", conversationId: null, onConversationCreated: noop }),
      { wrapper },
    );

    act(() => {
      result.current.addFiles([new File(["x"], "smlouva.pdf", { type: "application/pdf" })]);
    });
    act(() => {
      result.current.sendQuestion("Je smlouva platná?");
    });

    await waitFor(() => expect(result.current.queuedQuestion).toBe("Je smlouva platná?"));
    expect(sentBodies).toHaveLength(0);

    act(() => releaseUpload());

    await waitFor(() => expect(sentBodies).toHaveLength(1));
    expect(sentBodies[0]).toEqual({
      question: "Je smlouva platná?",
      attachment_ids: ["a-1"],
    });

    /*
     * The stream cannot carry the question's own files, so the user message has to be built
     * with them here — byte-identical to what GET /history will serve after a reload.
     */
    expect(result.current.messages[0].parts).toEqual([
      {
        type: "data-attachments",
        data: {
          items: [{ id: "a-1", filename: "smlouva.pdf", mime: "application/pdf", byte_size: 7 }],
        },
      },
      expect.objectContaining({ type: "text", text: "Je smlouva platná?" }),
    ]);
  });

  it("reports a send that failed before it left the client, and re-sends it on retry", async () => {
    let attempts = 0;
    server.use(
      http.post("http://api.test/conversations", () => {
        attempts += 1;
        return attempts === 1
          ? HttpResponse.json({ detail: "internal server error" }, { status: 500 })
          : HttpResponse.json(createdConversation);
      }),
      http.get("http://api.test/conversations", () => HttpResponse.json([createdConversation])),
      http.post("http://api.test/conversations/c1/messages", () => streamBody()),
    );

    const { result } = renderHook(
      () =>
        useChatSession({ sessionKey: "new-1", conversationId: null, onConversationCreated: noop }),
      { wrapper },
    );

    act(() => {
      result.current.sendQuestion("Je smlouva platná?");
    });

    // The queued bubble has to give way to the failure, not spin on forever.
    await waitFor(() => expect(result.current.hasSendFailed).toBe(true));
    expect(result.current.queuedQuestion).toBeNull();
    expect(result.current.isBusy).toBe(false);

    act(() => {
      result.current.retryLastTurn();
    });

    await waitFor(() => expect(result.current.messages).toHaveLength(2));
    expect(result.current.hasSendFailed).toBe(false);
  });

  it("ignores a second question while the turn is still under way", async () => {
    let releaseStream: () => void = () => undefined;
    const streamGate = new Promise<void>((resolve) => {
      releaseStream = resolve;
    });
    const sentBodies: unknown[] = [];

    server.use(
      http.post("http://api.test/conversations", () => HttpResponse.json(createdConversation)),
      http.get("http://api.test/conversations", () => HttpResponse.json([createdConversation])),
      http.post("http://api.test/conversations/c1/messages", async ({ request }) => {
        sentBodies.push(await request.json());
        await streamGate;
        return streamBody();
      }),
    );

    const { result } = renderHook(
      () =>
        useChatSession({ sessionKey: "new-1", conversationId: null, onConversationCreated: noop }),
      { wrapper },
    );

    act(() => {
      result.current.sendQuestion("Je smlouva platná?");
    });
    await waitFor(() => expect(sentBodies).toHaveLength(1));
    expect(result.current.isBusy).toBe(true);

    act(() => {
      result.current.sendQuestion("A co odstupné?");
    });
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(sentBodies).toHaveLength(1);

    act(() => releaseStream());
    await waitFor(() => expect(result.current.status).toBe("ready"));
  });

  it("refuses to send with no source and no attachment", async () => {
    useSourceScopeStore.getState().reset([]);
    const sent: unknown[] = [];
    server.use(
      http.post("http://api.test/conversations", () => HttpResponse.json(createdConversation)),
      http.post("http://api.test/conversations/c1/messages", async ({ request }) => {
        sent.push(await request.json());
        return streamBody();
      }),
    );

    const { result } = renderHook(
      () =>
        useChatSession({ sessionKey: "new-1", conversationId: null, onConversationCreated: noop }),
      { wrapper },
    );

    expect(result.current.canSend).toBe(false);
    act(() => {
      result.current.sendQuestion("Je smlouva platná?");
    });

    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(sent).toHaveLength(0);
  });

  it("streams an answer into messages", async () => {
    server.use(
      http.post("http://api.test/conversations", () => HttpResponse.json(createdConversation)),
      http.get("http://api.test/conversations", () => HttpResponse.json([createdConversation])),
      http.post("http://api.test/conversations/c1/messages", () => streamBody()),
    );

    const { result } = renderHook(
      () =>
        useChatSession({ sessionKey: "new-1", conversationId: null, onConversationCreated: noop }),
      { wrapper },
    );

    act(() => {
      result.current.sendQuestion("Je smlouva platná?");
    });

    await waitFor(() => expect(result.current.messages).toHaveLength(2));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(JSON.stringify(result.current.messages[1].parts)).toContain("Ano.");
  });

  it("attaches a file without creating a conversation for it", async () => {
    const created: unknown[] = [];
    server.use(
      http.post("http://api.test/conversations", async ({ request }) => {
        created.push(await request.json());
        return HttpResponse.json(createdConversation);
      }),
      http.post("http://api.test/attachments", () =>
        HttpResponse.json(
          {
            id: "a-1",
            filename: "smlouva.pdf",
            mime: "application/pdf",
            byte_size: 7,
            status: "indexed",
          },
          { status: 201 },
        ),
      ),
    );

    const { result } = renderHook(
      () =>
        useChatSession({ sessionKey: "new-1", conversationId: null, onConversationCreated: noop }),
      { wrapper },
    );

    act(() => {
      result.current.addFiles([new File(["x"], "smlouva.pdf", { type: "application/pdf" })]);
    });

    await waitFor(() => expect(result.current.uploads[0]?.status).toBe("ready"));
    // A thread born from an attachment alone would sit untitled and empty in the sidebar.
    expect(created).toHaveLength(0);
  });

  it("names the new thread from the question, so the sidebar shows it right away", async () => {
    const created: { title?: string }[] = [];
    server.use(
      http.post("http://api.test/conversations", async ({ request }) => {
        created.push((await request.json()) as { title?: string });
        return HttpResponse.json({ ...createdConversation, title: "Je smlouva platná?" });
      }),
      http.get("http://api.test/conversations", () =>
        HttpResponse.json([{ ...createdConversation, title: created[0]?.title ?? "" }]),
      ),
      http.post("http://api.test/conversations/c1/messages", () => streamBody()),
    );

    const { result } = renderHook(
      () => ({
        session: useChatSession({
          sessionKey: "new-1",
          conversationId: null,
          onConversationCreated: noop,
        }),
        conversations: useConversations(),
      }),
      { wrapper },
    );

    act(() => {
      result.current.session.sendQuestion("Je smlouva platná?");
    });

    await waitFor(() => expect(created).toHaveLength(1));
    expect(created[0].title).toBe("Je smlouva platná?");
    await waitFor(() =>
      expect(result.current.conversations.data?.[0].title).toBe("Je smlouva platná?"),
    );
  });

  it("does not refetch the conversation list after a turn in an existing thread", async () => {
    const titled = { ...createdConversation, title: "Platnost smlouvy" };
    let listRequests = 0;
    server.use(
      http.get("http://api.test/conversations", () => {
        listRequests += 1;
        return HttpResponse.json([titled]);
      }),
      http.post("http://api.test/conversations/c1/messages", () => streamBody()),
    );

    const { result } = renderHook(
      () => ({
        session: useChatSession({
          sessionKey: "c1",
          conversationId: "c1",
          onConversationCreated: noop,
        }),
        conversations: useConversations(),
      }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.conversations.data).toHaveLength(1));

    act(() => {
      result.current.session.sendQuestion("Je smlouva platná?");
    });

    await waitFor(() => expect(result.current.session.status).toBe("ready"));
    expect(listRequests).toBe(1);
  });
});
