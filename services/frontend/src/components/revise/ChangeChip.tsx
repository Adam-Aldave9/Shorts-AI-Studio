import { cn } from "@/lib/cn";

const TONES: Record<string, string> = {
  new: "border-success/40 bg-success/10 text-success",
  changed: "border-accent/40 bg-accent/10 text-accent-soft",
  edited: "border-accent/40 bg-accent/10 text-accent-soft",
  prompt: "border-accent/30 bg-accent/5 text-accent-soft",
  narration: "border-accent/30 bg-accent/5 text-accent-soft",
  renamed: "border-accent/30 bg-accent/5 text-accent-soft",
  stale: "border-warning/40 bg-warning/10 text-warning",
  removed: "border-danger/40 bg-danger/10 text-danger",
  kept: "border-border bg-surface text-fg-subtle",
};

const LABELS: Record<string, string> = {
  edited: "prompt rewritten",
  prompt: "prompt rewritten (world or style changed)",
  narration: "new narration",
  stale: "will be re-planned",
};

export function ChangeChip({ status, className }: { status: string; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-[11px] font-medium",
        TONES[status] ?? TONES.kept,
        className,
      )}
    >
      {LABELS[status] ?? status}
    </span>
  );
}

/** A small status dot for dense rails. */
export function ChangeDot({ status }: { status: string | undefined }) {
  if (!status) return null;
  const color =
    status === "new"
      ? "bg-success"
      : status === "stale"
        ? "bg-warning"
        : status === "removed"
          ? "bg-danger"
          : "bg-accent";
  return (
    <span
      className={cn("h-1.5 w-1.5 shrink-0 rounded-full", color)}
      title={LABELS[status] ?? status}
    />
  );
}
