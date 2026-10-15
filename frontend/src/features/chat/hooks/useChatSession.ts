import { useCallback, useMemo, useRef, useState } from "react";
import { useChat } from "@ai-sdk/react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import { useAttachmentUploads } from "@/features/attachments";
import { conversationQueryKeys } from "@/features/conversations";
import { useSourceScopeStore } from "@/features/sources";
import { translateError } from "@/lib/errors";
import { createChatTransport } from "../api/chat-transport";
import { historyQueryKeys } from "../api/history-api";
import type { LawAgentUIMessage } from "../types";
import { useEnsureConversation } from "./useEnsureConversation";

type UseChatSessionOptions = {
  /*
   * Remounts the chat state, so messages never leak between threads. Deliberately not
   * the conversation id: a new chat that gains one mid-send must keep its instance.
   */
  sessionKey: string;
  conversationId: string | null;
  initialMessages?: LawAgentUIMessage[];
  /** Fires once the lazily created thread exists, before the router is sent there. */
  onConversationCreated: (id: string) => void;
};

export type ChatSession = ReturnType<typeof useChatSession>;

export const useChatSession = ({
  sessionKey,
  conversationId,
  initialMessages,
  onConversationCreated,
}: UseChatSessionOptions) => {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const scope = useSourceScopeStore((state) => state.scope);
  const attachmentIdsRef = useRef<string[]>([]);
  const [queuedQuestion, setQueuedQuestion] = useState<string | null>(null);
  /*
   * A send that never reached the wire, so useChat knows nothing about it and there is no
   * assistant message to regenerate from. The question is kept so retrying can re-send it.
   */
  const [failedQuestion, setFailedQuestion] = useState<string | null>(null);

  const { ensureConversation, conversationIdRef } = useEnsureConversation(
    conversationId,
    onConversationCreated,
  );
  /*
   * Read per request, never during render: an upload started in a new chat carries no
   * conversation, while one started after the thread exists is claimed by it immediately.
   */
  const getConversationId = useCallback(() => conversationIdRef.current, [conversationIdRef]);
  const uploads = useAttachmentUploads(getConversationId);

  const transport = useMemo(() => {
    /*
     * The getters run inside prepareSendMessagesRequest, per request — never during
     * render. That is how the URL learns the conversation id created moments earlier,
     * which is exactly what the rule cannot tell apart from a render-time read.
     */
    // eslint-disable-next-line react-hooks/refs -- see above
    return createChatTransport({
      getConversationId: () => conversationIdRef.current,
      getAttachmentIds: () => attachmentIdsRef.current,
    });
  }, [conversationIdRef]);

  const chat = useChat<LawAgentUIMessage>({
    id: sessionKey,
    messages: initialMessages,
    transport,
    onError: (error) => {
      /*
       * A 404 here is never a missing thread — the send endpoint also answers 404 for an
       * attachment id that is not a pending attachment of this conversation. Dropping the
       * stale chips lets the user resend instead of being thrown out of a live thread.
       */
      if (translateError(error).status === 404) {
        attachmentIdsRef.current = [];
        uploads.clear();
      }
    },
    onFinish: () => {
      /*
       * The turn reaches the archive only now, so the cached history predates it. Without
       * this, leaving the thread and coming back rehydrates the chat from before the turn.
       */
      const id = conversationIdRef.current;
      if (id === null) return;

      void queryClient.invalidateQueries({ queryKey: historyQueryKeys.detail(id) });
    },
  });

  const hasAttachment = uploads.uploads.some((upload) => upload.status !== "error");
  /*
   * The source rule governs the creation of a thread, not its life: an existing thread has
   * its scope frozen server-side, and the picker is in-memory only — empty after a reload.
   */
  const canSend = conversationId !== null || scope.length > 0 || hasAttachment;
  /*
   * One notion of "a turn is already under way", covering the wait for uploads as well as the
   * stream itself — the composer disables both its button and the Enter key from it.
   */
  const isBusy =
    queuedQuestion !== null || chat.status === "submitted" || chat.status === "streaming";

  const { sendMessage } = chat;
  const { waitForReadyAttachments, clear: clearUploads } = uploads;

  const sendQuestion = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      // With no source and no attachment the agent has nothing to search.
      if (trimmed.length === 0 || !canSend || isBusy) return;

      const wasNewThread = conversationIdRef.current === null;
      setQueuedQuestion(trimmed);
      setFailedQuestion(null);

      void (async () => {
        try {
          // The send waits for every in-flight upload; those uploads need no thread of their
          // own, so the question — which also names the thread — decides when one is created.
          const attachments = await waitForReadyAttachments();
          const id = await ensureConversation(trimmed);
          // The transport reads both refs synchronously once sendMessage fires.
          attachmentIdsRef.current = attachments.map((attachment) => attachment.id);
          setQueuedQuestion(null);
          clearUploads();

          /*
           * The attachments part is composed here rather than left to the stream, which cannot
           * carry it, and in the order history serves it: files first, then the question. A turn
           * without files gets no part at all — history never sends an empty items list either.
           */
          sendMessage({
            parts: [
              ...(attachments.length > 0
                ? [{ type: "data-attachments" as const, data: { items: attachments } }]
                : []),
              { type: "text", text: trimmed },
            ],
          });

          if (wasNewThread) {
            // The thread is named at creation, so this single refetch puts a titled row in
            // the sidebar; nothing about it changes once the turn finishes.
            void queryClient.invalidateQueries({ queryKey: conversationQueryKeys.all });
            void navigate(`/chat/${id}`, { replace: true });
          }
        } catch {
          /*
           * Creating the thread is the step that can fail here, and it fails before anything
           * is on screen. Without this the queued bubble would spin forever on a question the
           * composer has already cleared, so the question is handed to the retry affordance.
           */
          setQueuedQuestion(null);
          setFailedQuestion(trimmed);
        }
      })();
    },
    [
      canSend,
      clearUploads,
      conversationIdRef,
      ensureConversation,
      isBusy,
      navigate,
      queryClient,
      sendMessage,
      waitForReadyAttachments,
    ],
  );

  const { regenerate } = chat;

  const retryLastTurn = useCallback(() => {
    // A failed send left no turn behind to regenerate; it has to be sent for the first time.
    // sendQuestion clears the failure itself, but only once it is past its own guards.
    if (failedQuestion !== null) {
      sendQuestion(failedQuestion);
      return;
    }
    void regenerate();
  }, [failedQuestion, regenerate, sendQuestion]);

  /*
   * One affordance on the chip, two server-side meanings: aborting an in-flight upload
   * is not the same call as deleting one that already resolved.
   */
  const dismissUpload = useCallback(
    (localId: string) => {
      const upload = uploads.uploads.find((entry) => entry.localId === localId);
      if (upload?.status === "ready") {
        void uploads.remove(localId);
        return;
      }
      uploads.cancel(localId);
    },
    [uploads],
  );

  return {
    /** Identity of the chat state; changes when the screen switches to another thread. */
    sessionKey,
    messages: chat.messages,
    status: chat.status,
    error: chat.error,
    /** True when the last send never reached the server, so nothing of it is in `messages`. */
    hasSendFailed: failedQuestion !== null,
    queuedQuestion,
    uploads: uploads.uploads,
    hasPendingUploads: uploads.hasPendingUploads,
    canSend,
    isBusy,
    sendQuestion,
    retryLastTurn,
    addFiles: uploads.addFiles,
    dismissUpload,
    retryUpload: uploads.retry,
  };
};
