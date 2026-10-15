import { useEffect, useRef } from "react";
import { ChatScreen } from "@/features/chat";
import { useSourceScopeStore } from "@/features/sources";

export const NewChatPage = () => {
  const reset = useSourceScopeStore((state) => state.reset);
  const isLocked = useSourceScopeStore((state) => state.isLocked);
  const hasResetRef = useRef(false);

  useEffect(() => {
    /*
     * Only a locked store belongs to a thread that is now behind us; a store prefilled
     * by "Nový chat s jinými zdroji" is already unlocked and must survive.
     */
    if (hasResetRef.current) return;
    hasResetRef.current = true;
    if (isLocked) reset();
  }, [isLocked, reset]);

  return <ChatScreen />;
};
