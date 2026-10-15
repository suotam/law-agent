import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { RoleSummary, UserResponse } from "@/features/auth";
import { roleQueryKeys } from "@/features/roles";
import { userQueryKeys } from "./query-keys";

type UpdateUserRoleRequest = {
  id: string;
  role_id: string;
};

export const updateUserRole = async ({
  id,
  role_id,
}: UpdateUserRoleRequest): Promise<UserResponse> => {
  const { data } = await apiClient.patch<UserResponse>(`/users/${id}`, { role_id });
  return data;
};

export const useUpdateUserRole = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: updateUserRole,
    // The row's <select> reads its value straight from this list query, so
    // without an optimistic write here `mutate()` alone (via `isPending`)
    // forces a re-render before the PATCH resolves, and the controlled
    // select snaps back to the still-cached old role until the request
    // settles -- a visible flicker to the old value and back.
    onMutate: async ({ id, role_id }) => {
      await queryClient.cancelQueries({ queryKey: userQueryKeys.list });
      const previousUsers = queryClient.getQueryData<UserResponse[]>(userQueryKeys.list);
      const newRole = queryClient
        .getQueryData<RoleSummary[]>(roleQueryKeys.list)
        ?.find((role) => role.id === role_id);

      if (newRole !== undefined) {
        queryClient.setQueryData<UserResponse[]>(userQueryKeys.list, (current) =>
          current?.map((user) => (user.id === id ? { ...user, role: newRole } : user)),
        );
      }

      return { previousUsers };
    },
    onError: (_error, _variables, context) => {
      if (context?.previousUsers !== undefined) {
        queryClient.setQueryData(userQueryKeys.list, context.previousUsers);
      }
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: userQueryKeys.list });
    },
  });
};
