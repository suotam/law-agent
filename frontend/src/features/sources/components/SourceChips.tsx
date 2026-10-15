import { useTranslation } from "react-i18next";
import type { ScopeValue } from "@/features/conversations";
import { cn } from "@/lib/utils";
import { useOrgFilesScopeStore } from "../org-files-scope-store";
import { SCOPE_VALUES, useSourceScopeStore } from "../source-scope-store";
import { OrgFilesScopePicker } from "./OrgFilesScopePicker";

export const SCOPE_LABEL_KEYS = {
  laws: "sources.laws",
  org_files: "sources.orgFiles",
} as const satisfies Record<ScopeValue, string>;

type SourceChipsProps = {
  /** Set while the "scope or attachment" rule is unmet, to point at the remedy. */
  isHighlighted?: boolean;
  className?: string;
};

export const SourceChips = ({ isHighlighted = false, className }: SourceChipsProps) => {
  const { t } = useTranslation();
  const scope = useSourceScopeStore((state) => state.scope);
  const isLocked = useSourceScopeStore((state) => state.isLocked);
  const toggle = useSourceScopeStore((state) => state.toggle);
  const clearOrgFilesScope = useOrgFilesScopeStore((state) => state.clear);

  const onToggle = (value: ScopeValue) => {
    // org_files carries a narrowing selection that only makes sense while
    // the namespace itself is active; turning it off must not leave a
    // stale, invisible selection behind for the next time it is turned on.
    if (value === "org_files" && scope.includes(value)) clearOrgFilesScope();
    toggle(value);
  };

  return (
    <div className={cn("flex flex-col items-center gap-2", className)}>
      <div className="flex flex-wrap items-center justify-center gap-2">
        {SCOPE_VALUES.map((value) => {
          const isActive = scope.includes(value);

          return (
            <button
              key={value}
              type="button"
              aria-pressed={isActive}
              disabled={isLocked}
              onClick={() => onToggle(value)}
              className={cn(
                "rounded-lg border px-3 py-1.5 text-sm transition-colors disabled:opacity-60",
                isActive
                  ? "bg-source-chip-active-bg text-source-chip-active-fg border-transparent"
                  : "bg-background text-foreground hover:bg-muted",
                isHighlighted && !isActive && "border-warning ring-warning/40 ring-2",
              )}
            >
              {t(SCOPE_LABEL_KEYS[value])}
            </button>
          );
        })}
      </div>
      {scope.includes("org_files") && <OrgFilesScopePicker />}
    </div>
  );
};
