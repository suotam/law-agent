import { useEffect, useState } from "react";
import { LoaderCircle } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";

const spinnerSizes = {
  sm: "size-4",
  md: "size-6",
  lg: "size-10",
} as const;

type LoadingProps = {
  size?: keyof typeof spinnerSizes;
  /** Visible text under the spinner. Falls back to a screen-reader-only label. */
  label?: string;
  /** Centers the spinner in the whole viewport, e.g. while bootstrapping the app. */
  fullScreen?: boolean;
  /** Suppresses the spinner for this many ms so it does not flash on a fast connection. */
  delayMs?: number;
  className?: string;
};

export const Loading = ({
  size = "md",
  label,
  fullScreen = false,
  delayMs = 0,
  className,
}: LoadingProps) => {
  const { t } = useTranslation();
  const [isVisible, setIsVisible] = useState(delayMs === 0);

  useEffect(() => {
    if (delayMs === 0) return;

    const timer = setTimeout(() => setIsVisible(true), delayMs);
    return () => clearTimeout(timer);
  }, [delayMs]);

  if (!isVisible) return null;

  return (
    <div
      role="status"
      aria-busy="true"
      className={cn(
        "flex flex-col items-center justify-center gap-3",
        fullScreen && "min-h-svh",
        className,
      )}
    >
      <LoaderCircle
        aria-hidden="true"
        className={cn("text-muted-foreground animate-spin", spinnerSizes[size])}
      />
      {label ? (
        <p className="text-muted-foreground text-sm">{label}</p>
      ) : (
        <span className="sr-only">{t("common.loading")}</span>
      )}
    </div>
  );
};
