import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MessageList, type LawAgentUIMessage } from "@/features/chat";

const question: LawAgentUIMessage = {
  id: "u1",
  role: "user",
  parts: [{ type: "text", text: "Do kdy lze odstoupit?" }],
};

const assistantWith = (parts: LawAgentUIMessage["parts"]): LawAgentUIMessage => ({
  id: "a1",
  role: "assistant",
  parts,
});

type ListProps = Parameters<typeof MessageList>[0];

const renderList = (props: Partial<ListProps> = {}) =>
  render(
    <MessageList
      messages={[]}
      queuedQuestion={null}
      status="ready"
      error={undefined}
      hasSendFailed={false}
      onRetry={vi.fn()}
      {...props}
    />,
  );

describe("MessageList", () => {
  it("reports document processing while the question waits for its uploads", () => {
    renderList({ queuedQuestion: "Do kdy lze odstoupit?" });

    expect(screen.getByText("Zpracovávám dokumenty…")).toBeInTheDocument();
  });

  it("reports thinking once the question is sent", () => {
    renderList({ messages: [question], status: "submitted" });

    expect(screen.getByText("Přemýšlím…")).toBeInTheDocument();
  });

  it("keeps reporting thinking while the stream carries only sources", () => {
    renderList({
      messages: [question, assistantWith([{ type: "data-sources", data: { items: [] } }])],
      status: "streaming",
    });

    expect(screen.getByText("Přemýšlím…")).toBeInTheDocument();
  });

  it("drops the indicator on the first token of the answer", () => {
    renderList({
      messages: [question, assistantWith([{ type: "text", text: "Do 14" }])],
      status: "streaming",
    });

    expect(screen.queryByText("Přemýšlím…")).not.toBeInTheDocument();
  });

  it("shows no indicator on a settled thread", () => {
    renderList({
      messages: [question, assistantWith([{ type: "text", text: "Do 14 dnů." }])],
      status: "ready",
    });

    expect(screen.queryByText(/Přemýšlím|Zpracovávám/)).not.toBeInTheDocument();
  });

  it("streams the last answer, so its sources stay unlisted until it finishes", () => {
    renderList({
      messages: [
        question,
        assistantWith([
          { type: "text", text: "Do 14 dnů [1]." },
          {
            type: "data-sources",
            data: { items: [{ ref: 1, kind: "law", label: "§ 1829 obč. zák.", content: {} }] },
          },
        ]),
      ],
      status: "streaming",
    });

    expect(screen.getByText("Zdroje načteny (1)")).toBeInTheDocument();
    expect(screen.queryByText("§ 1829 obč. zák.")).not.toBeInTheDocument();
  });

  it("lists the files a question was sent with", () => {
    renderList({
      messages: [
        {
          ...question,
          parts: [
            {
              type: "data-attachments",
              data: {
                items: [
                  { id: "a-1", filename: "smlouva.pdf", mime: "application/pdf", byte_size: 7 },
                ],
              },
            },
            ...question.parts,
          ],
        },
      ],
    });

    expect(screen.getByText("smlouva.pdf")).toBeInTheDocument();
    expect(screen.getByText("Do kdy lze odstoupit?")).toBeInTheDocument();
  });

  it("shows no attachment list on a question sent without files", () => {
    renderList({ messages: [question] });

    expect(screen.queryByRole("list", { name: "Přílohy zprávy" })).not.toBeInTheDocument();
  });

  it("resolves a citation against a source an earlier turn found", () => {
    renderList({
      messages: [
        question,
        {
          ...assistantWith([
            { type: "text", text: "Do 14 dnů [1]." },
            {
              type: "data-sources",
              data: { items: [{ ref: 1, kind: "law", label: "§ 1829 obč. zák.", content: {} }] },
            },
          ]),
          id: "a1",
        },
        { ...question, id: "u2" },
        // The second answer cites the first turn's source and carries no data-sources of its own.
        { ...assistantWith([{ type: "text", text: "Jak už bylo řečeno [1]." }]), id: "a2" },
      ],
      status: "ready",
    });

    expect(screen.getAllByRole("button", { name: "Zdroj 1: § 1829 obč. zák." })).toHaveLength(2);
    expect(screen.getAllByText("§ 1829 obč. zák.")).toHaveLength(2);
  });
});
