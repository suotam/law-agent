import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  AssistantMessage,
  buildThreadSources,
  type LawAgentUIMessage,
  type SourceItem,
  type ThreadSources,
} from "@/features/chat";

const sourceItem: SourceItem = {
  ref: 1,
  kind: "law",
  label: "§ 1829 obč. zák.",
  content: { chunk: "irrelevant", score: 0.9 },
};

const messageWithParts = (id: string): LawAgentUIMessage => ({
  id,
  role: "assistant",
  parts: [
    { type: "text", text: "Do 14 dnů [1] můžete odstoupit." },
    { type: "data-sources", data: { items: [sourceItem] } },
  ],
});

/** A lone message stands in for the whole thread unless the case needs a wider map. */
const renderMessage = (
  message: LawAgentUIMessage,
  options: { threadSources?: ThreadSources; isStreaming?: boolean } = {},
) =>
  render(
    <AssistantMessage
      message={message}
      threadSources={options.threadSources ?? buildThreadSources([message])}
      isStreaming={options.isStreaming}
    />,
  );

describe("AssistantMessage", () => {
  it("renders a citation marker as a link to its source label", () => {
    renderMessage(messageWithParts("m1"));

    const citation = screen.getByRole("button", { name: "Zdroj 1: § 1829 obč. zák." });
    expect(citation).toHaveTextContent("1");
    expect(screen.getByText("§ 1829 obč. zák.")).toBeInTheDocument();
  });

  it("never renders the opaque content dict", () => {
    const { container } = renderMessage(messageWithParts("m1"));

    expect(container.textContent).not.toContain("[object Object]");
    expect(container.textContent).not.toContain("irrelevant");
  });

  it("produces identical output for a stream part and a history part", () => {
    // The two paths differ only in the message id; the parts array is byte-identical.
    const fromStream = renderMessage(messageWithParts("stream-id"));
    const streamHtml = fromStream.container.innerHTML;
    fromStream.unmount();

    const fromHistory = renderMessage(messageWithParts("history-id"));

    expect(fromHistory.container.innerHTML).toBe(streamHtml);
  });

  it("leaves a marker with no source in the thread as plain text", () => {
    renderMessage({
      id: "m2",
      role: "assistant",
      parts: [{ type: "text", text: "Podle [7] to neplatí." }],
    });

    expect(screen.getByText(/Podle \[7\] to neplatí\./)).toBeInTheDocument();
  });

  it("resolves a marker against a source this turn never carried", () => {
    // Refs are numbered per conversation: [2] was found while answering an earlier question.
    const earlier: SourceItem = { ...sourceItem, ref: 2, label: "§ 1820 obč. zák." };
    const message: LawAgentUIMessage = {
      id: "m8",
      role: "assistant",
      parts: [{ type: "text", text: "Jak už bylo řečeno [2]." }],
    };

    renderMessage(message, { threadSources: new Map([[2, earlier]]) });

    expect(screen.getByRole("button", { name: "Zdroj 2: § 1820 obč. zák." })).toBeInTheDocument();
    expect(screen.getByText("§ 1820 obč. zák.")).toBeInTheDocument();
  });

  it("substitutes markers inside markdown structure without breaking it", () => {
    renderMessage({
      id: "m3",
      role: "assistant",
      parts: [
        { type: "text", text: "- **Lhůta** je 14 dnů [1]\n- Druhá položka" },
        { type: "data-sources", data: { items: [sourceItem] } },
      ],
    });

    // The first list is the answer's own; the second is the source list below it.
    const [answerList] = screen.getAllByRole("list");
    expect(within(answerList).getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("Lhůta").tagName).toBe("STRONG");
    expect(screen.getByRole("button", { name: "Zdroj 1: § 1829 obč. zák." })).toBeInTheDocument();
  });

  it("lists only the sources the answer cites", () => {
    renderMessage({
      id: "m4",
      role: "assistant",
      parts: [
        { type: "text", text: "Do 14 dnů [1] můžete odstoupit." },
        {
          type: "data-sources",
          data: { items: [sourceItem, { ...sourceItem, ref: 2, label: "§ 1820 obč. zák." }] },
        },
      ],
    });

    expect(screen.getByText("§ 1829 obč. zák.")).toBeInTheDocument();
    expect(screen.queryByText("§ 1820 obč. zák.")).not.toBeInTheDocument();
  });

  it("lists cited sources in ref order, whichever turn found them", () => {
    const message: LawAgentUIMessage = {
      id: "m9",
      role: "assistant",
      parts: [
        { type: "text", text: "Nejdřív [3], pak [1]." },
        { type: "data-sources", data: { items: [{ ...sourceItem, ref: 3, label: "§ 1837" }] } },
      ],
    };

    renderMessage(message, {
      threadSources: new Map([
        [1, sourceItem],
        [3, { ...sourceItem, ref: 3, label: "§ 1837" }],
      ]),
    });

    // The answer is a paragraph, so the only list on screen is the source list.
    const labels = within(screen.getByRole("list"))
      .getAllByRole("listitem")
      .map((item) => item.textContent);
    expect(labels).toEqual(["1§ 1829 obč. zák.", "3§ 1837"]);
  });

  it("renders no source section when the answer cites nothing", () => {
    renderMessage({
      id: "m5",
      role: "assistant",
      parts: [
        { type: "text", text: "Na to nemám podklad." },
        { type: "data-sources", data: { items: [sourceItem] } },
      ],
    });

    expect(screen.queryByText("Zdroje")).not.toBeInTheDocument();
    expect(screen.queryByText("§ 1829 obč. zák.")).not.toBeInTheDocument();
  });

  it("announces loaded sources instead of listing them while streaming", () => {
    renderMessage(messageWithParts("m6"), { isStreaming: true });

    // Filtering needs the whole answer: a source cited last would flicker in late.
    expect(screen.getByText("Zdroje načteny (1)")).toBeInTheDocument();
    expect(screen.queryByText("§ 1829 obč. zák.")).not.toBeInTheDocument();
  });

  it("counts only what this turn found, not the whole thread's map", () => {
    const message: LawAgentUIMessage = {
      id: "m10",
      role: "assistant",
      parts: [{ type: "data-sources", data: { items: [sourceItem] } }],
    };

    renderMessage(message, {
      threadSources: new Map([
        [1, sourceItem],
        [2, { ...sourceItem, ref: 2, label: "§ 1820 obč. zák." }],
      ]),
      isStreaming: true,
    });

    expect(screen.getByText("Zdroje načteny (1)")).toBeInTheDocument();
  });

  it("stays silent about sources that have not arrived yet", () => {
    renderMessage(
      { id: "m7", role: "assistant", parts: [{ type: "text", text: "Do 14" }] },
      { isStreaming: true },
    );

    expect(screen.queryByText(/Zdroje/)).not.toBeInTheDocument();
  });
});
