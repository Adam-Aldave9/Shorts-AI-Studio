import { cn } from "@/lib/cn";

type ProgressTone = "accent" | "warning" | "danger" | "success";

const TONE_FILL: Record<ProgressTone, string> = {
  accent: "bg-accent",
  warning: "bg-warning",
  danger: "bg-danger",
  success: "bg-success",
};

/** A determinate bar. `fraction` is 0-1 and is clamped; `label` is what a screen reader
 *  hears, so pass something that names the quantity, not just "progress". */
export function ProgressBar({
  fraction,
  label,
  tone = "accent",
  className,
}: {
  fraction: number;
  label: string;
  tone?: ProgressTone;
  className?: string;
}) {
  const clamped = Number.isFinite(fraction) ? Math.min(1, Math.max(0, fraction)) : 0;
  const percent = Math.round(clamped * 100);
  return (
    <div
      className={cn("h-1.5 overflow-hidden rounded-full bg-surface-overlay", className)}
      role="progressbar"
      aria-valuenow={percent}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label}
    >
      <div
        className={cn("h-full rounded-full transition-all duration-500", TONE_FILL[tone])}
        style={{ width: `${percent}%` }}
      />
    </div>
  );
}

/** The same track with no known fraction: a band sweeping across it. Used while a stage
 *  is working but has not reported a `done / total` yet — an honest alternative to
 *  animating a made-up percentage. */
export function IndeterminateBar({ label, className }: { label: string; className?: string }) {
  return (
    <div
      className={cn("h-1.5 overflow-hidden rounded-full bg-surface-overlay", className)}
      role="progressbar"
      aria-label={label}
    >
      <div className="h-full w-1/3 rounded-full bg-accent/70 animate-progress-sweep" />
    </div>
  );
}
