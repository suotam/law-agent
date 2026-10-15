import type { ChatStatus } from "ai";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { useThreadSources } from "../hooks/useThreadSources";
import { AssistantMessage } from "./AssistantMessage";
import { PendingTurn } from "./PendingTurn";
import { UserMessage } from "./UserMessage";
import type { LawAgentUIMessage } from "../types";

type MessageListProps = {
  messages: LawAgentUIMessage[];
  queuedQuestion: string | null;
  status: ChatStatus;
  error: Error | undefined;
  /** A send that never reached the server; it has no message of its own to fail on. */
  hasSendFailed: boolean;
  onRetry: () => void;
};

const hasText = (message: LawAgentUIMessage | undefined): boolean =>
  message?.parts.some((part) => part.type === "text" && part.text.length > 0) ?? false;

const isTurnPending = (messages: LawAgentUIMessage[], status: ChatStatus): boolean => {
  if (status === "submitted") return true;
  // Sources arrive before the model starts writing, so they do not end the wait.
  return status === "streaming" && !hasText(messages.at(-1));
};

export const MessageList = ({
  messages,
  queuedQuestion,
  status,
  error,
  hasSendFailed,
  onRetry,
}: MessageListProps) => {
  const { t } = useTranslation();
  const lastIndex = messages.length - 1;
  // Refs are numbered per conversation, so resolving them is the thread's job, not a message's.
  const threadSources = useThreadSources(messages);

  const pendingLabel =
    queuedQuestion !== null
      ? t("chat.processingDocuments")
      : isTurnPending(messages, status)
        ? t("chat.thinking")
        : null;

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 p-4">
      {messages.map((message, index) =>
        message.role === "user" ? (
          <UserMessage
            key={message.id}
            message={message}
          />
        ) : (
          <AssistantMessage
            key={message.id}
            message={message}
            threadSources={threadSources}
            // Only the last message can still be growing; the rest are settled.
            isStreaming={index === lastIndex && (status === "submitted" || status === "streaming")}
          />
        ),
      )}

      {queuedQuestion !== null && (
        <p className="bg-chat-user-bubble/60 text-chat-user-bubble-foreground max-w-[80%] self-end rounded-xl px-3 py-2">
          {queuedQuestion}
        </p>
      )}

      {pendingLabel !== null && <PendingTurn label={pendingLabel} />}

      {(error || hasSendFailed) && (
        <div
          role="alert"
          className="border-destructive/40 flex items-center gap-3 rounded-lg border p-3"
        >
          {/* errorText from the stream is a prepared Czech sentence carrying no server
              detail, so it is safe to show; anything else falls back to a generic line. */}
          <p className="text-destructive text-sm">
            {hasSendFailed ? t("chat.sendFailed") : error?.message || t("chat.streamError")}
          </p>
          <Button
            variant="outline"
            size="sm"
            onClick={onRetry}
          >
            {t("common.retry")}
          </Button>
        </div>
      )}
    </div>
  );
};
