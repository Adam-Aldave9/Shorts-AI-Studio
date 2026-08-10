import type { ReactNode } from "react";
import type { Asset } from "@/api/client";
import { formatTimecode } from "@/lib/format";
import { Button, cn } from "@/components/ui";
import { ShotChip } from "./ShotChip";

export interface SceneView {
  id: string;
  heading: string;
  location: string;
  beat: string;
  narration: string;
  shots: Asset[];
  span: { in_s: number; out_s: number } | null;
}

function Block({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-fg-subtle">{label}</div>
      <div className="mt-1.5">{children}</div>
    </div>
  );
}

export function SceneDetail({
  scene,
  position,
  total,
  onMove,
  onSeek,
}: {
  scene: SceneView;
  position: number;
  total: number;
  onMove: (delta: number) => void;
  onSeek: (nodeId: string) => void;
}) {
  const first = scene.shots[0];

  return (
    <div className="flex min-h-0 flex-col rounded-xl border bg-surface-raised">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b px-5 py-3">
        <h3 className="text-sm font-semibold text-fg">{scene.heading}</h3>
        {scene.location && (
          <span className="rounded-full border bg-surface-overlay px-2 py-0.5 text-xs text-fg-muted">
            {scene.location}
          </span>
        )}
        {scene.span && (
          <span className="text-xs tabular-nums text-fg-subtle">
            {formatTimecode(scene.span.in_s)}-{formatTimecode(scene.span.out_s)}
          </span>
        )}
        {first && (
          <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => onSeek(first.node_id)}>
            Play from here
          </Button>
        )}
        <div className="ml-auto flex items-center gap-1">
          <button
            type="button"
            aria-label="Previous scene"
            disabled={position <= 1}
            onClick={() => onMove(-1)}
            className={cn(
              "rounded px-2 py-0.5 text-sm text-fg-muted transition hover:text-fg disabled:opacity-30",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60",
            )}
          >
            {"<"}
          </button>
          <span className="tabular-nums text-xs text-fg-subtle">
            {position} of {total}
          </span>
          <button
            type="button"
            aria-label="Next scene"
            disabled={position >= total}
            onClick={() => onMove(1)}
            className={cn(
              "rounded px-2 py-0.5 text-sm text-fg-muted transition hover:text-fg disabled:opacity-30",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60",
            )}
          >
            {">"}
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-5 py-4">
        {scene.beat && (
          <Block label="What you see">
            <p className="text-sm leading-relaxed text-fg-muted">{scene.beat}</p>
          </Block>
        )}
        {scene.narration && (
          <Block label="What you hear">
            <blockquote className="border-l-2 border-accent/40 pl-3 text-sm leading-relaxed text-fg">
              {scene.narration}
            </blockquote>
          </Block>
        )}
        {scene.shots.length > 0 && (
          <Block label={`Shots (${scene.shots.length})`}>
            <div className="flex flex-wrap gap-1.5">
              {scene.shots.map((shot) => (
                <ShotChip key={shot.node_id} shot={shot} onSeek={onSeek} />
              ))}
            </div>
          </Block>
        )}
      </div>
    </div>
  );
}
