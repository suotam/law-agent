import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { server } from "@/test/msw/server";
import { useDeleteAclEntry } from "../api/acl-mutations";
import { useUserAcl } from "@/features/users";

describe("useDeleteAclEntry", () => {
  it("invalidates the user's own ACL cache for a user-principal entry, refetching it", async () => {
    const requested = vi.fn();
    server.use(
      http.get("http://api.test/users/u1/acl", () => {
        requested();
        return HttpResponse.json({ entries: [], folders_with_nested_grant: [] });
      }),
      http.delete("http://api.test/acl/:id", () => new HttpResponse(null, { status: 204 })),
    );

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );

    renderHook(() => useUserAcl("u1"), { wrapper });
    await waitFor(() => expect(requested).toHaveBeenCalledTimes(1));

    const { result } = renderHook(() => useDeleteAclEntry(), { wrapper });
    result.current.mutate({
      id: "acl1",
      resource_type: "folder",
      resource_id: "f1",
      principal_type: "user",
      principal_id: "u1",
      permission: "read",
      created_at: "2026-08-01T00:00:00Z",
    });

    await waitFor(() => expect(requested).toHaveBeenCalledTimes(2));
  });
});
