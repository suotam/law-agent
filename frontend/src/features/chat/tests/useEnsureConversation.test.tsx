import { renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it } from "vitest";
import { server } from "@/test/msw/server";
import { useEnsureConversation } from "@/features/chat";
import { useOrgFilesScopeStore, useSourceScopeStore } from "@/features/sources";

const noop = () => undefined;

const wrapper = ({ children }: { children: ReactNode }) => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
};

/** Records every POST /conversations body the hook produces. */
const recordCreateCalls = (): unknown[] => {
  const bodies: unknown[] = [];
  server.use(
    http.post("http://api.test/conversations", async ({ request }) => {
      bodies.push(await request.json());
      return HttpResponse.json({
        id: "c1",
        title: "",
        created_at: "2026-08-01T00:00:00Z",
        updated_at: "2026-08-01T00:00:00Z",
      });
    }),
  );
  return bodies;
};

describe("useEnsureConversation", () => {
  beforeEach(() => {
    useSourceScopeStore.getState().reset();
    useOrgFilesScopeStore.getState().clear();
  });

  it("creates exactly one conversation when two sends race", async () => {
    const bodies = recordCreateCalls();
    const { result } = renderHook(() => useEnsureConversation(null, noop), { wrapper });

    const [first, second] = await Promise.all([
      result.current.ensureConversation("Je smlouva platná?"),
      result.current.ensureConversation("Je smlouva platná?"),
    ]);

    expect(bodies).toHaveLength(1);
    expect(first).toBe("c1");
    expect(second).toBe("c1");
  });

  it("always sends scope, including an empty array", async () => {
    const bodies = recordCreateCalls();
    const { result } = renderHook(() => useEnsureConversation(null, noop), { wrapper });

    await result.current.ensureConversation("Je smlouva platná?");

    expect(bodies[0]).toEqual({ scope: [], title: "Je smlouva platná?" });
  });

  /*
   * The server no longer names a thread from its first question, and there is no rename
   * endpoint — a creation without a title leaves the sidebar row blank forever.
   */
  it("names the thread at creation time from the question it was given", async () => {
    const bodies = recordCreateCalls();
    const { result } = renderHook(() => useEnsureConversation(null, noop), { wrapper });

    await result.current.ensureConversation("Do kdy lze odstoupit od smlouvy?");

    expect(bodies[0]).toMatchObject({ title: "Do kdy lze odstoupit od smlouvy?" });
  });

  it("sends the chips as they stand when it fires", async () => {
    const bodies = recordCreateCalls();
    useSourceScopeStore.getState().toggle("org_files");
    const { result } = renderHook(() => useEnsureConversation(null, noop), { wrapper });

    await result.current.ensureConversation("Je smlouva platná?");

    expect(bodies[0]).toMatchObject({ scope: ["org_files"] });
  });

  it("locks the chips once the conversation resolves", async () => {
    recordCreateCalls();
    const { result } = renderHook(() => useEnsureConversation(null, noop), { wrapper });

    expect(useSourceScopeStore.getState().isLocked).toBe(false);
    await result.current.ensureConversation("Je smlouva platná?");

    expect(useSourceScopeStore.getState().isLocked).toBe(true);
  });

  it("returns an existing id without creating anything", async () => {
    const bodies = recordCreateCalls();
    const { result } = renderHook(() => useEnsureConversation("existing-id", noop), { wrapper });

    await expect(result.current.ensureConversation("Je smlouva platná?")).resolves.toBe(
      "existing-id",
    );
    expect(bodies).toHaveLength(0);
  });

  it("sends both narrowing fields once anything is checked, `[]` for the untouched side", async () => {
    /*
     * Narrowing is one decision about the whole selection: a folder-only
     * check must still send `org_files_document_ids: []`, or the server
     * would leave unrelated direct document grants searchable.
     */
    const bodies = recordCreateCalls();
    useOrgFilesScopeStore.getState().toggleFolder("folder-1");
    const { result } = renderHook(() => useEnsureConversation(null, noop), { wrapper });

    await result.current.ensureConversation("Je smlouva platná?");

    expect(bodies[0]).toMatchObject({
      org_files_folder_ids: ["folder-1"],
      org_files_document_ids: [],
    });
  });

  it("omits both narrowing fields when nothing was checked", async () => {
    const bodies = recordCreateCalls();
    useOrgFilesScopeStore.getState().toggleDocument("doc-1");
    useOrgFilesScopeStore.getState().toggleDocument("doc-1");
    const { result } = renderHook(() => useEnsureConversation(null, noop), { wrapper });

    await result.current.ensureConversation("Je smlouva platná?");

    expect(bodies[0]).toEqual({ scope: [], title: "Je smlouva platná?" });
  });

  it("lets a later caller retry after a failed creation", async () => {
    let attempts = 0;
    server.use(
      http.post("http://api.test/conversations", () => {
        attempts += 1;
        if (attempts === 1) return HttpResponse.json({ detail: "boom" }, { status: 500 });
        return HttpResponse.json({
          id: "c2",
          title: "",
          created_at: "2026-08-01T00:00:00Z",
          updated_at: "2026-08-01T00:00:00Z",
        });
      }),
    );
    const { result } = renderHook(() => useEnsureConversation(null, noop), { wrapper });

    await expect(result.current.ensureConversation("Je smlouva platná?")).rejects.toBeDefined();
    await expect(result.current.ensureConversation("Je smlouva platná?")).resolves.toBe("c2");
  });
});
