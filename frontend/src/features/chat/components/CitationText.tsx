import { Fragment, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { MARKER_PATTERN, type ThreadSources } from "../utils/citations";

type CitationTextProps = {
  text: string;
  sources: ThreadSources;
};

/*
 * Substitution runs on a single text node, not on the whole answer: markdown owns the
 * string first, so splitting before it parses would break lists and emphasis.
 */
export const CitationText = ({ text, sources }: CitationTextProps) => {
  const { t } = useTranslation();
  const segments: ReactNode[] = [];
  let lastIndex = 0;

  for (const match of text.matchAll(MARKER_PATTERN)) {
    const ref = Number(match[1]);
    const source = sources.get(ref);
    // A ref the thread never offered is the model inventing one; it stays literal text.
    if (source === undefined) continue;

    const start = match.index;
    segments.push(text.slice(lastIndex, start));
    segments.push(
      <button
        key={`${start}-${ref}`}
        type="button"
        aria-label={t("chat.citationLabel", { ref, label: source.label })}
        onClick={() => document.getElementById(`source-${ref}`)?.scrollIntoView()}
        className="bg-citation-marker-bg text-citation-fg mx-0.5 rounded px-1 align-super text-xs"
      >
        {ref}
      </button>,
    );
    lastIndex = start + match[0].length;
  }

  segments.push(text.slice(lastIndex));

  return (
    <>
      {segments.map((segment, index) => (
        <Fragment key={index}>{segment}</Fragment>
      ))}
    </>
  );
};
