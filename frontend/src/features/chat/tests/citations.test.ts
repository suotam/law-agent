import { describe, expect, it } from "vitest";
import {
  buildThreadSources,
  collectCitedRefs,
  threadSourcesSignature,
  type LawAgentUIMessage,
  type SourceItem,
} from "@/features/chat";

const law: SourceItem = { ref: 1, kind: "law", label: "§ 1829 obč. zák.", content: {} };

const answerWith = (id: string, items: SourceItem[]): LawAgentUIMessage => ({
  id,
  role: "assistant",
  parts: [{ type: "data-sources", data: { items } }],
});

describe("collectCitedRefs", () => {
  it("returns nothing for text without markers", () => {
    expect(collectCitedRefs("Odstoupit lze do 14 dnů.")).toEqual(new Set());
  });

  it("collects every distinct ref", () => {
    expect(collectCitedRefs("Podle [1] a [3] to platí.")).toEqual(new Set([1, 3]));
  });

  it("counts a repeated marker once", () => {
    expect(collectCitedRefs("[2] a znovu [2]")).toEqual(new Set([2]));
  });

  it("reads multi-digit refs whole", () => {
    expect(collectCitedRefs("Viz [12].")).toEqual(new Set([12]));
  });

  it("ignores a bracket that holds no number", () => {
    expect(collectCitedRefs("Odkaz [viz níže] a [1].")).toEqual(new Set([1]));
  });
});

describe("buildThreadSources", () => {
  it("merges the sources of every turn into one map", () => {
    const second: SourceItem = { ...law, ref: 2, label: "§ 1820 obč. zák." };

    const sources = buildThreadSources([answerWith("a1", [law]), answerWith("a2", [second])]);

    expect([...sources.keys()]).toEqual([1, 2]);
    expect(sources.get(2)).toBe(second);
  });

  it("keeps the source a ref was first given when the ref comes back", () => {
    const repeated = { ...law };

    const sources = buildThreadSources([answerWith("a1", [law]), answerWith("a2", [repeated])]);

    expect(sources.get(1)).toBe(law);
  });

  it("collects sources the answer never cited", () => {
    const uncited: SourceItem = { ...law, ref: 2, label: "§ 1820 obč. zák." };

    // data-sources is what the search found, not what the answer used.
    expect(buildThreadSources([answerWith("a1", [law, uncited])]).size).toBe(2);
  });

  it("ignores messages that carry no sources", () => {
    const question: LawAgentUIMessage = {
      id: "u1",
      role: "user",
      parts: [{ type: "text", text: "Do kdy lze odstoupit?" }],
    };

    expect(buildThreadSources([question]).size).toBe(0);
  });
});

describe("threadSourcesSignature", () => {
  it("stays the same when only the answer text grows", () => {
    const withText = (text: string): LawAgentUIMessage => ({
      id: "a1",
      role: "assistant",
      parts: [
        { type: "text", text },
        { type: "data-sources", data: { items: [law] } },
      ],
    });

    expect(threadSourcesSignature([withText("Do 14")])).toBe(
      threadSourcesSignature([withText("Do 14 dnů [1].")]),
    );
  });

  it("changes when a turn brings a source the thread did not have", () => {
    const before = [answerWith("a1", [law])];
    const after = [...before, answerWith("a2", [{ ...law, ref: 2, label: "§ 1820" }])];

    expect(threadSourcesSignature(after)).not.toBe(threadSourcesSignature(before));
  });
});
