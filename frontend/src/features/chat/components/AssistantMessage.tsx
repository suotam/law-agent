import { memo, useMemo } from "react";
import { collectCitedRefs, collectSourceItems, type ThreadSources } from "../utils/citations";
import { MarkdownAnswer } from "./MarkdownAnswer";
import { SourceList } from "./SourceList";
import type { LawAgentUIMessage } from "../types";

const collectText = (message: LawAgentUIMessage): string =>
  message.parts.map((part) => (part.type === "text" ? part.text : "")).join("");

type AssistantMessageProps = {
  message: LawAgentUIMessage;
  /** Every source the thread knows, since an answer may cite one found several turns ago. */
  threadSources: ThreadSources;
  /** True only for the turn currently being written; history is finished by definition. */
  isStreaming?: boolean;
};

/*
 * Memoised because a single token re-renders the whole list, and every settled answer above the
 * streaming one would otherwise re-parse its markdown and rescan its citations on each frame.
 */
export const AssistantMessage = memo(function AssistantMessage({
  message,
  threadSources,
  isStreaming = false,
}: AssistantMessageProps) {
  // What this turn's own search found — the number reported while the answer is still writing.
  const foundCount = useMemo(() => collectSourceItems(message).length, [message]);
  const text = useMemo(() => collectText(message), [message]);
  const citedRefs = useMemo(() => collectCitedRefs(text), [text]);

  return (
    <article className="bg-chat-assistant-bg text-foreground rounded-xl px-1 py-2">
      <MarkdownAnswer
        text={text}
        sources={threadSources}
      />
      <SourceList
        sources={threadSources}
        citedRefs={citedRefs}
        foundCount={foundCount}
        isStreaming={isStreaming}
      />
    </article>
  );
});
