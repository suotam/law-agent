import { LoaderCircle } from "lucide-react";

type PendingTurnProps = {
  label: string;
};

/*
 * The wait between sending and the first token is long enough to read as a broken app,
 * so it gets a voice — and the label says which of the two waits it is.
 */
export const PendingTurn = ({ label }: PendingTurnProps) => (
  <p
    aria-live="polite"
    className="text-muted-foreground flex items-center gap-2 text-sm"
  >
    <LoaderCircle
      aria-hidden="true"
      className="size-3.5 animate-spin"
    />
    {label}
  </p>
);
