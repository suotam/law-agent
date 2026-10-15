import { useTranslation } from "react-i18next";
import { Skeleton } from "@/components/ui/skeleton";
import { ConversationListItem } from "./ConversationListItem";
import { CONVERSATION_LIST_CAP, useConversations } from "../hooks/useConversations";

export const ConversationList = () => {
  const { t } = useTranslation();
  const { data, isPending, isError } = useConversations();

  if (isPending) {
    return (
      <div className="flex flex-col gap-1.5 p-1">
        {Array.from({ length: 5 }, (_, index) => (
          <Skeleton
            key={index}
            className="h-7 w-full"
          />
        ))}
      </div>
    );
  }

  if (isError) {
    return (
      <p className="text-sidebar-foreground/70 px-2 text-sm">{t("conversations.loadError")}</p>
    );
  }

  if (data.length === 0) {
    return <p className="text-sidebar-foreground/70 px-2 text-sm">{t("conversations.empty")}</p>;
  }

  return (
    <div className="flex flex-col gap-2">
      <ul className="flex flex-col gap-0.5">
        {data.map((conversation) => (
          <ConversationListItem
            key={conversation.id}
            conversation={conversation}
          />
        ))}
      </ul>
      {/* Older threads are simply unreachable; without this the list looks broken. */}
      {data.length >= CONVERSATION_LIST_CAP && (
        <p className="text-sidebar-foreground/60 px-2 text-xs">{t("conversations.capNotice")}</p>
      )}
    </div>
  );
};
