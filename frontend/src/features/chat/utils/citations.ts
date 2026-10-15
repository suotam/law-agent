import type { LawAgentUIMessage, SourceItem } from "../types";

/*
 * One definition of "cited": the source list and the in-text markers are derived from the
 * same scan, so they can never disagree about which sources the answer used.
 */
export const MARKER_PATTERN = /\[(\d+)\]/g;

export const collectCitedRefs = (text: string): Set<number> =>
  new Set([...text.matchAll(MARKER_PATTERN)].map((match) => Number(match[1])));

/*
 * The stream and the history endpoint emit data-sources identically, so this reads the
 * same for both paths and the renderer above them is written once.
 */
export const collectSourceItems = (message: LawAgentUIMessage): SourceItem[] =>
  message.parts.flatMap((part) => (part.type === "data-sources" ? part.data.items : []));

/** Every source the thread has been offered so far, keyed by the ref it was given. */
export type ThreadSources = ReadonlyMap<number, SourceItem>;

/*
 * A ref is unique for the whole conversation, so an answer may cite a source that was first
 * offered several questions ago and is absent from its own data-sources part. Resolving
 * against the accumulated map is what keeps that citation from being dropped — or, worse,
 * from pointing at a different source. A ref that comes back keeps the source it already
 * had, which makes the write idempotent.
 */
export const buildThreadSources = (messages: LawAgentUIMessage[]): ThreadSources => {
  const sources = new Map<number, SourceItem>();

  for (const message of messages) {
    for (const item of collectSourceItems(message)) {
      if (!sources.has(item.ref)) sources.set(item.ref, item);
    }
  }

  return sources;
};

/** Changes only when the thread learns of a source it did not have; see `useThreadSources`. */
export const threadSourcesSignature = (messages: LawAgentUIMessage[]): string =>
  messages
    .flatMap((message) => collectSourceItems(message).map((item) => `${item.ref}:${item.label}`))
    .join("|");
