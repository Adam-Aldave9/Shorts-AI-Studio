import { cn } from "@/lib/cn";

// Colored text/border over a ~10% tinted fill. Status hues are semantic (executing
// blue, succeeded green, ...) and stay literal here rather than going through tokens.
const NODE_COLORS: Record<string, string> = {
  pending: "bg-surface-overlay/60 text-fg-muted border-border",
  dispatched: "bg-blue-500/10 text-blue-300 border-blue-500/30",
  succeeded: "bg-green-500/10 text-green-300 border-green-500/30",
  failed: "bg-red-500/10 text-red-300 border-red-500/30",
  "dead-lettered": "bg-rose-500/15 text-rose-300 border-rose-500/40",
};

// Live states get a pulsing status dot for at-a-glance liveness.
const LIVE_STATES = new Set(["dispatched", "executing", "compositing"]);

function StatusDot({ live }: { live: boolean }) {
  return (
    <span
      className={cn(
        "mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-current",
        live && "animate-pulse",
      )}
    />
  );
}

export function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium",
        NODE_COLORS[status] ?? NODE_COLORS.pending,
      )}
    >
      <StatusDot live={LIVE_STATES.has(status)} />
      {status}
    </span>
  );
}

const PHASE_COLORS: Record<string, string> = {
  queued: "bg-surface-overlay/60 text-fg-muted border-border",
  executing: "bg-blue-500/10 text-blue-300 border-blue-500/30",
  compositing: "bg-indigo-500/10 text-indigo-300 border-indigo-500/30",
  complete: "bg-green-500/10 text-green-300 border-green-500/30",
  blocked: "bg-amber-500/10 text-amber-300 border-amber-500/30",
  paused: "bg-amber-500/10 text-amber-300 border-amber-500/30",
};

export function PhaseBadge({ phase }: { phase: string | null }) {
  const label = phase ?? "queued";
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium capitalize",
        PHASE_COLORS[label] ?? PHASE_COLORS.queued,
      )}
    >
      <StatusDot live={LIVE_STATES.has(label)} />
      {label}
    </span>
  );
}
