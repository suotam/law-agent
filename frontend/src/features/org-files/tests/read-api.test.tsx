import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { server } from "@/test/msw/server";
import { useFolderLevel } from "../api/get-folders";

const wrapper = ({ children }: { children: ReactNode }) => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
};

describe("useFolderLevel", () => {
  it("lists the caller's roots at the top level", async () => {
    const requested = vi.fn();
    server.use(
      http.get("http://api.test/me/org-files/roots", () => {
        requested();
        return HttpResponse.json([
          {
            id: "f1",
            name: "Smlouvy",
            ancestor_path: "",
            effective_permission: "write",
            is_structure_manager: false,
          },
        ]);
      }),
    );

    const { result } = renderHook(() => useFolderLevel(null), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(requested).toHaveBeenCalledTimes(1);
    expect(result.current.data?.folders[0].effective_permission).toBe("write");
    // Documents never live above a folder, so the root level has none.
    expect(result.current.data?.files).toEqual([]);
  });

  it("lists a folder's subfolders and documents in one call", async () => {
    server.use(
      http.get("http://api.test/me/org-files/folders/f1", () =>
        HttpResponse.json({
          folders: [
            {
              id: "f2",
              parent_id: "f1",
              name: "2026",
              created_at: "2026-08-01T00:00:00Z",
              effective_permission: "read",
              is_structure_manager: false,
            },
          ],
          files: [
            {
              id: "d1",
              filename: "smlouva.pdf",
              mime: "application/pdf",
              byte_size: 12,
              status: "indexed",
              effective_permission: "read",
              is_structure_manager: false,
            },
          ],
        }),
      ),
    );

    const { result } = renderHook(() => useFolderLevel("f1"), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.folders).toHaveLength(1);
    expect(result.current.data?.files[0].filename).toBe("smlouva.pdf");
  });

  it("reports a rejected level instead of pretending it is empty", async () => {
    server.use(
      http.get(
        "http://api.test/me/org-files/folders/f1",
        () => new HttpResponse(null, { status: 404 }),
      ),
    );

    const { result } = renderHook(() => useFolderLevel("f1"), { wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});
