import { create } from "zustand";
import { persist } from "zustand/middleware";

type TokenState = {
  token: string | null;
  setToken: (token: string | null) => void;
};

/*
 * The token is client state, not server state: keeping it in React Query would let
 * queryClient.clear() on logout drop it while requests are still in flight.
 */
export const useTokenStore = create<TokenState>()(
  persist(
    (set) => ({
      token: null,
      setToken: (token) => set({ token }),
    }),
    { name: "law-agent-auth" },
  ),
);

export const getToken = (): string | null => useTokenStore.getState().token;

export const setToken = (token: string): void => useTokenStore.getState().setToken(token);

export const clearToken = (): void => useTokenStore.getState().setToken(null);
