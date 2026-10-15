import { useMemo } from "react";
import { buildThreadSources, threadSourcesSignature, type ThreadSources } from "../utils/citations";
import type { LawAgentUIMessage } from "../types";

/*
 * `messages` gets a new identity on every streamed token, so memoising on it would hand each
 * settled answer a fresh map per frame and defeat the memo on AssistantMessage. The map only
 * changes when the thread is offered a source it did not have, which the signature captures —
 * hence the signature, not `messages`, is the dependency.
 */
export const useThreadSources = (messages: LawAgentUIMessage[]): ThreadSources => {
  const signature = threadSourcesSignature(messages);

  // eslint-disable-next-line react-hooks/exhaustive-deps -- signature stands in for messages
  return useMemo(() => buildThreadSources(messages), [signature]);
};
