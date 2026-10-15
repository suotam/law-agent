import { useTranslation } from "react-i18next";
import type { ThreadSources } from "../utils/citations";

type SourceListProps = {
  /** The whole thread's sources; only the subset this answer cites is ever listed. */
  sources: ThreadSources;
  citedRefs: Set<number>;
  /** How many sources this turn's own search returned, reported while the answer writes. */
  foundCount: number;
  isStreaming: boolean;
};

export const SourceList = ({ sources, citedRefs, foundCount, isStreaming }: SourceListProps) => {
  const { t } = useTranslation();

  /*
   * Filtering needs the finished answer — a source cited in the last paragraph would
   * otherwise flicker into a list the user is already reading. Until then, only the
   * fact that retrieval delivered something is reported, in the list's own place.
   */
  if (isStreaming) {
    if (foundCount === 0) return null;

    return (
      <section className="border-border mt-3 border-t pt-3">
        <p className="text-muted-foreground text-xs font-medium">
          {t("chat.sourcesLoaded", { total: foundCount })}
        </p>
      </section>
    );
  }

  /*
   * Ordered by ref rather than by the order the marks appear: refs are handed out in the
   * order the thread discovered its sources, so the list reads the way it is numbered. A
   * mark with no source behind it is the model inventing one and is left out.
   */
  const cited = [...citedRefs]
    .map((ref) => sources.get(ref))
    .filter((source) => source !== undefined)
    .sort((left, right) => left.ref - right.ref);

  if (cited.length === 0) return null;

  return (
    <section className="border-border mt-3 border-t pt-3">
      <h3 className="text-muted-foreground mb-1.5 text-xs font-medium">
        {t("chat.sourcesHeading")}
      </h3>
      <ol className="flex flex-col gap-1">
        {cited.map((source) => (
          <li
            key={source.ref}
            id={`source-${source.ref}`}
            className="text-citation-fg text-sm"
          >
            <span className="bg-citation-marker-bg mr-1.5 rounded px-1 text-xs">{source.ref}</span>
            {/* label is the only human-readable field; content is opaque and never rendered. */}
            {source.label}
          </li>
        ))}
      </ol>
    </section>
  );
};
