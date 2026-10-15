import { useMutation, useQueryClient } from "@tanstack/react-query";
import { login } from "../api/auth-api";
import { setToken } from "../token-store";
import { authQueryKeys } from "./useAuth";

export const useLogin = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: login,
    onSuccess: async (data) => {
      setToken(data.access_token);
      // /auth/me is disabled while no token exists, so it must be refetched
      // explicitly once the token appears.
      await queryClient.invalidateQueries({ queryKey: authQueryKeys.me });
    },
  });
};
