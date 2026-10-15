import type { UIMessage } from "ai";
import type { MessageAttachment } from "@/features/attachments";

export type SourceKind = "law" | "document";

export type SourceItem = {
  ref: number;
  kind: SourceKind;
  /** The only human-readable field, e.g. "§ 1829 obč. zák.". */
  label: string;
  /** Opaque dict shaped by whichever tool produced the hit. Never rendered. */
  content: Record<string, unknown>;
};

export type LawAgentDataParts = {
  sources: { items: SourceItem[] };
  /*
   * The files a question was sent with. History serves this part on the user message, but the
   * stream never can — a data frame is appended to the answer being streamed, and these belong
   * to the question. The live turn therefore composes an identical part client-side.
   */
  attachments: { items: MessageAttachment[] };
};

/** The backend emits no metadata and no tool parts, so both slots stay empty. */
export type LawAgentUIMessage = UIMessage<never, LawAgentDataParts>;

export type SendMessageRequest = {
  question: string;
  attachment_ids: string[];
};
