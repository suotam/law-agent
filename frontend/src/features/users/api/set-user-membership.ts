import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { groupQueryKeys, type GroupResponse } from "@/features/groups";
import { userQueryKeys } from "./query-keys";

type SetUserMembershipInput = { groupId: string; member: boolean };

/** Adds or removes one user's membership of one group, reusing the same
 * endpoints the group-centric editor drives -- only the cache bookkeeping is
 * user-centric, because this hook's callers read membership user-side.
 * Optimistic: the checkbox must not flicker back while the POST/DELETE is in
 * flight, the same reason `useUpdateUserRole` writes the list cache eagerly. */
export const useSetUserMembership = (userId: string) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ groupId, member }: SetUserMembershipInput) => {
      if (member) await apiClient.post(`/groups/${groupId}/members`, { user_id: userId });
      else await apiClient.delete(`/groups/${groupId}/members/${userId}`);
    },
    onMutate: async ({ groupId, member }) => {
      await queryClient.cancelQueries({ queryKey: userQueryKeys.groups(userId) });
      const previous = queryClient.getQueryData<GroupResponse[]>(userQueryKeys.groups(userId));
      if (previous !== undefined) {
        queryClient.setQueryData<GroupResponse[]>(
          userQueryKeys.groups(userId),
          member
            ? [...previous, { id: groupId, name: "", created_at: "" }]
            : previous.filter((group) => group.id !== groupId),
        );
      }
      return { previous };
    },
    onError: (_error, _input, context) => {
      if (context?.previous !== undefined)
        queryClient.setQueryData(userQueryKeys.groups(userId), context.previous);
    },
    onSettled: (_data, _error, { groupId }) => {
      void queryClient.invalidateQueries({ queryKey: userQueryKeys.groups(userId) });
      void queryClient.invalidateQueries({ queryKey: groupQueryKeys.members(groupId) });
    },
  });
};
