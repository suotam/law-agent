import { useCallback, useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { conversationQueryKeys, createConversation } from "@/features/conversations";
import { getOrgFilesScope, getScope, lockOrgFilesScope, lockScope } from "@/features/sources";

/**
 * @param title Names the thread on creation; the server truncates it and offers no rename
 *   later, so a thread created without one stays blank in the sidebar forever.
 */
export type EnsureConversation = (title: string) => Promise<string>;

/*
 * The transport needs an id synchronously when it builds the URL, but the thread does not
 * exist until the user sends. A single in-flight promise held in a ref makes a second
 * caller await the first instead of creating a duplicate thread.
 */
export const useEnsureConversation = (
  existingId: string | null,
  /** Must be referentially stable; it is a dependency of the returned callback. */
  onCreated: (id: string) => void,
) => {
  const queryClient = useQueryClient();
  const conversationIdRef = useRef<string | null>(existingId);
  const pendingRef = useRef<Promise<string> | null>(null);

  // Opening an existing thread hands the id in as a prop; the ref is what the
  // transport reads, so the two are kept in step here rather than during render.
  useEffect(() => {
    conversationIdRef.current = existingId;
  }, [existingId]);

  const ensureConversation = useCallback<EnsureConversation>(
    (title) => {
      if (conversationIdRef.current !== null) return Promise.resolve(conversationIdRef.current);
      if (pendingRef.current !== null) return pendingRef.current;

      const { folderIds, documentIds } = getOrgFilesScope();
      // The omit-vs-send decision belongs to the whole narrowing action, not
      // to each field: once the user checked anything, both fields go out --
      // `[]` for the untouched side -- or the server would treat that side as
      // "no narrowing" and keep unrelated direct grants searchable.
      const narrowed = folderIds.length > 0 || documentIds.length > 0;
      const pending = createConversation({
        scope: getScope(),
        title,
        ...(narrowed
          ? { org_files_folder_ids: folderIds, org_files_document_ids: documentIds }
          : {}),
      })
        .then((conversation) => {
          conversationIdRef.current = conversation.id;
          // The chips must stop looking editable the moment the scope is settled server-side.
          lockScope();
          lockOrgFilesScope();
          void queryClient.invalidateQueries({ queryKey: conversationQueryKeys.all });
          // The session now belongs to a thread; whoever owns it has to learn the id
          // before the router is sent there, or the arrival looks like a cold open.
          onCreated(conversation.id);
          return conversation.id;
        })
        .finally(() => {
          // Cleared either way so a failed creation can be retried by the next caller.
          pendingRef.current = null;
        });

      pendingRef.current = pending;
      return pending;
    },
    [onCreated, queryClient],
  );

  return { ensureConversation, conversationIdRef };
};
