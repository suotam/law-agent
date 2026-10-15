import { Children, Fragment, type ReactNode } from "react";
import Markdown from "react-markdown";
import { CitationText } from "./CitationText";
import type { ThreadSources } from "../utils/citations";

type MarkdownAnswerProps = {
  text: string;
  sources: ThreadSources;
};

/*
 * react-markdown has no override for text nodes — its `components` map is keyed by HTML
 * element — so citation substitution is applied to the string children of the elements
 * that can contain prose. Markdown parses first, so structure is never split apart.
 */
const withCitations = (children: ReactNode, sources: ThreadSources): ReactNode =>
  Children.map(children, (child, index) =>
    typeof child === "string" ? (
      <CitationText
        key={index}
        text={child}
        sources={sources}
      />
    ) : (
      <Fragment key={index}>{child}</Fragment>
    ),
  );

export const MarkdownAnswer = ({ text, sources }: MarkdownAnswerProps) => (
  <div className="flex flex-col gap-3 text-sm leading-relaxed [&_li]:ml-4 [&_ol]:list-decimal [&_strong]:font-semibold [&_ul]:list-disc">
    <Markdown
      components={{
        p: ({ children }) => <p>{withCitations(children, sources)}</p>,
        li: ({ children }) => <li>{withCitations(children, sources)}</li>,
        strong: ({ children }) => <strong>{withCitations(children, sources)}</strong>,
        em: ({ children }) => <em>{withCitations(children, sources)}</em>,
      }}
    >
      {text}
    </Markdown>
  </div>
);
