import { memo } from "react";
import { MessageAttachments } from "@/features/attachments";
import type { LawAgentUIMessage } from "../types";

type UserMessageProps = {
  message: LawAgentUIMessage;
};

/* Memoised for the same reason as AssistantMessage: every token re-renders the whole list. */
export const UserMessage = memo(function UserMessage({ message }: UserMessageProps) {
  // flatMap rather than find: it narrows the part union on its own and unwraps the items.
  const attachments = message.parts.flatMap((part) =>
    part.type === "data-attachments" ? part.data.items : [],
  );

  return (
    <article className="flex flex-col items-end gap-1.5">
      <p className="bg-chat-user-bubble text-chat-user-bubble-foreground max-w-[80%] rounded-xl px-3 py-2 whitespace-pre-wrap">
        {message.parts.map((part) => (part.type === "text" ? part.text : "")).join("")}
      </p>
      <MessageAttachments items={attachments} />
    </article>
  );
});
