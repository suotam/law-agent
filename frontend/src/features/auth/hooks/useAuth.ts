import { useQuery } from "@tanstack/react-query";
import { getCurrentUser } from "../api/auth-api";
import { useTokenStore } from "../token-store";
import type { UserResponse } from "../types";

export const authQueryKeys = {
  me: ["auth", "me"] as const,
};

type UseAuthResult = {
  user: UserResponse | undefined;
  isAuthenticated: boolean;
  isLoadingAuth: boolean;
};

/*
 * The token is validated against the server rather than decoded client-side: a JWT's
 * own claims cannot tell us whether the account still exists.
 */
export const useAuth = (): UseAuthResult => {
  const token = useTokenStore((state) => state.token);

  const query = useQuery({
    queryKey: authQueryKeys.me,
    queryFn: getCurrentUser,
    enabled: token !== null,
    // The user does not change during a session.
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    retry: false,
  });

  return {
    user: query.data,
    isAuthenticated: token !== null && query.isSuccess,
    isLoadingAuth: token !== null && query.isPending,
  };
};
