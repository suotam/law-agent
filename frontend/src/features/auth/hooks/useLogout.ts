import { queryClient } from "@/lib/react-query";
import { clearToken } from "../token-store";

/*
 * The single reaction to a session ending, whether the user asked for it or a 401 did:
 * the axios interceptor and the chat transport call this too. Clearing the token flips
 * useAuth to unauthenticated and the route guard performs the redirect — no imperative
 * navigation from outside React, which is why this stays a plain function.
 */
export const clearSession = (): void => {
  clearToken();
  void queryClient.cancelQueries();
  queryClient.clear();
};

export const useLogout = () => ({ logout: clearSession });
