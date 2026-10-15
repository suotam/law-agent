import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router";
import { Loading } from "@/components/Loading";
import { ChatScreen, useChatSessionContext } from "@/features/chat";
import { useConversation } from "@/features/conversations";
import { FrozenScopeBadges } from "@/features/sources";
import { translateError } from "@/lib/errors";

export const ChatThreadPage = () => {
  const { id = "" } = useParams<{ id: string }>();
  const { t } = useTranslation();
  const navigate = useNavigate();
  const conversation = useConversation(id);
  // The session itself is hoisted above the router, so this page only reports on it.
  const { isHydrating, hydrationError } = useChatSessionContext();

  const isGone =
    translateError(conversation.error).status === 404 ||
    translateError(hydrationError).status === 404;

  useEffect(() => {
    /*
     * A 404 on the thread itself means gone — deleted, or someone else's. The backend
     * deliberately does not distinguish, so this is a quiet redirect, not an error panel.
     */
    if (isGone) void navigate("/", { replace: true });
  }, [isGone, navigate]);

  if (conversation.isPending || isHydrating) return <Loading delayMs={200} />;

  if (conversation.isError || hydrationError) {
    return <p className="text-destructive p-6 text-sm">{t("chat.historyError")}</p>;
  }

  return <ChatScreen header={<FrozenScopeBadges scope={conversation.data.scope} />} />;
};
