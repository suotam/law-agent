import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { SourceChips } from "@/features/sources";
import { cn } from "@/lib/utils";
import { useStickToBottom } from "../hooks/useStickToBottom";
import { useChatSessionContext } from "./ChatSessionProvider";
import { Composer } from "./Composer";
import { MessageList } from "./MessageList";

type ChatScreenProps = {
  /** Rendered in the header of an open thread; the new-chat screen has none. */
  header?: ReactNode;
};

export const ChatScreen = ({ header }: ChatScreenProps) => {
  const { t } = useTranslation();
  const { session, isNewChat } = useChatSessionContext();
  const { containerRef, scrollToBottom } = useStickToBottom(session.sessionKey);
  const isEmpty = session.messages.length === 0 && session.queuedQuestion === null;

  return (
    <main className="flex min-h-0 flex-1 flex-col">
      {header && (
        <header className="border-border flex shrink-0 items-center justify-end border-b p-2">
          {header}
        </header>
      )}

      <div
        className={cn(
          "flex min-h-0 flex-1 flex-col",
          // An empty screen centres its prompt; a running thread fills the height instead.
          isEmpty && "justify-center",
        )}
      >
        {isEmpty ? (
          <h1 className="mb-6 text-center text-2xl font-semibold tracking-tight">
            {t("chat.newChatHeading")}
          </h1>
        ) : (
          <div
            ref={containerRef}
            className="min-h-0 flex-1 overflow-y-auto"
          >
            <MessageList
              messages={session.messages}
              queuedQuestion={session.queuedQuestion}
              status={session.status}
              error={session.error}
              hasSendFailed={session.hasSendFailed}
              onRetry={session.retryLastTurn}
            />
          </div>
        )}

        <div className="flex shrink-0 flex-col gap-3 p-4">
          <Composer
            // A question sent from halfway up the thread still belongs at the bottom.
            onSubmit={(text) => {
              session.sendQuestion(text);
              scrollToBottom();
            }}
            onFiles={session.addFiles}
            isRuleUnmet={!session.canSend}
            isBusy={session.isBusy}
            uploads={session.uploads}
            onDismissUpload={session.dismissUpload}
            onRetryUpload={session.retryUpload}
          />
          {/* Sources get space and attention where they are decided: the new-chat screen. */}
          {isNewChat && <SourceChips isHighlighted={!session.canSend} />}
        </div>
      </div>
    </main>
  );
};
