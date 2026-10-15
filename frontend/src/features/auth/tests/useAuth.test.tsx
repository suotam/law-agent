import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { server } from "@/test/msw/server";
import { getToken, setToken, useAuth, useTokenStore } from "@/features/auth";

const wrapper = ({ children }: { children: ReactNode }) => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
};

describe("useAuth", () => {
  it("is unauthenticated and never calls the API when no token is stored", async () => {
    useTokenStore.getState().setToken(null);

    const { result } = renderHook(() => useAuth(), { wrapper });

    await waitFor(() => expect(result.current.isLoadingAuth).toBe(false));
    expect(result.current.isAuthenticated).toBe(false);
    expect(result.current.user).toBeUndefined();
  });

  it("authenticates by validating the token against /auth/me", async () => {
    setToken("token-123");
    server.use(
      http.get("http://api.test/auth/me", () =>
        HttpResponse.json({
          id: "u1",
          email: "jan@fir.cz",
          role: "member",
          created_at: "2026-08-01T00:00:00Z",
        }),
      ),
    );

    const { result } = renderHook(() => useAuth(), { wrapper });

    await waitFor(() => expect(result.current.isAuthenticated).toBe(true));
    expect(result.current.user?.email).toBe("jan@fir.cz");
    expect(result.current.user?.role).toBe("member");
  });

  it("clears a dead token when /auth/me answers 401", async () => {
    setToken("dead-token");
    server.use(
      http.get("http://api.test/auth/me", () =>
        HttpResponse.json({ detail: "not authenticated" }, { status: 401 }),
      ),
    );

    const { result } = renderHook(() => useAuth(), { wrapper });

    await waitFor(() => expect(getToken()).toBeNull());
    expect(result.current.isAuthenticated).toBe(false);
  });
});
