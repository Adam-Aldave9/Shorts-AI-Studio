import type { Asset } from "@/api/client";
import { shotDurationS } from "@/lib/package";
import { formatDuration } from "@/lib/format";
import { cn } from "@/components/ui";

const STATUS_DOT: Record<string, string> = {
  pending: "bg-fg-subtle",
  dispatched: "bg-blue-400",
  succeeded: "bg-green-400",
  failed: "bg-red-400",
  "dead-lettered": "bg-rose-400",
};

/** One shot as a compact, clickable token: status dot, node id, duration. Clicking seeks
 *  the final cut to where the shot lands. */
export function ShotChip({ shot, onSeek }: { shot: Asset; onSeek: (nodeId: string) => void }) {
  return (
    <button
      type="button"
      onClick={() => onSeek(shot.node_id)}
      title={shot.prompt ?? undefined}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border bg-surface-overlay px-2.5 py-1",
        "text-xs text-fg-muted transition hover:border-border-strong hover:text-fg",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:ring-offset-1 focus-visible:ring-offset-surface",
      )}
    >
      <span
        className={cn(
          "h-1.5 w-1.5 rounded-full",
          STATUS_DOT[shot.status ?? "pending"] ?? STATUS_DOT.pending,
        )}
      />
      <span className="font-mono">{shot.node_id}</span>
      <span className="tabular-nums text-fg-subtle">{formatDuration(shotDurationS(shot))}</span>
    </button>
  );
}
