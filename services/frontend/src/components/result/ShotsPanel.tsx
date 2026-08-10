// The Shots tab: every planned shot in playback order, next to what it actually cost and
// whether it rendered. The prompt is the draft the provider was handed.

import { useState } from "react";
import type { Asset, ProductionPackage } from "@/api/client";
import {
  narrativeShotByNode,
  referenceImages,
  scenes as narrativeScenes,
  shotDurationS,
  shotsInPlaybackOrder,
  timelineByNode,
} from "@/lib/package";
import { formatDuration, formatUsd } from "@/lib/format";
import { EmptyState, StatusBadge, cn } from "@/components/ui";
import { Panel } from "@/components/Panel";

function Prompt({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <button
      type="button"
      onClick={() => setExpanded((open) => !open)}
      title={expanded ? "Collapse" : "Expand"}
      className={cn(
        "block w-full text-left text-sm leading-relaxed text-fg-muted transition hover:text-fg",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:ring-offset-1 focus-visible:ring-offset-surface",
        !expanded && "line-clamp-2",
      )}
    >
      {text}
    </button>
  );
}

function Timing({ shot, entry }: { shot: Asset; entry?: { in_s: number; out_s: number } }) {
  return (
    <div className="tabular-nums">
      <div>{formatDuration(shotDurationS(shot))}</div>
      {entry && (
        <div className="text-xs text-fg-subtle">
          {entry.in_s.toFixed(1)}-{entry.out_s.toFixed(1)}s
        </div>
      )}
    </div>
  );
}

function Cost({ shot }: { shot: Asset }) {
  return (
    <div className="tabular-nums">
      <div>{formatUsd(shot.actual_cost_usd ?? shot.estimated_cost_usd ?? 0)}</div>
      {shot.actual_cost_usd != null && (
        <div className="text-xs text-fg-subtle">est. {formatUsd(shot.estimated_cost_usd ?? 0)}</div>
      )}
    </div>
  );
}

export function ShotsPanel({ pkg }: { pkg: ProductionPackage }) {
  const shots = shotsInPlaybackOrder(pkg);
  const byNode = narrativeShotByNode(pkg);
  const timeline = timelineByNode(pkg);
  const headingOf = new Map(narrativeScenes(pkg).map((scene) => [scene.id, scene.heading]));
  const refs = referenceImages(pkg);

  if (shots.length === 0) {
    return <EmptyState title="No shots">This package has no video nodes.</EmptyState>;
  }

  return (
    <div className="space-y-4">
      <Panel title={`Shots (${shots.length})`}>
        <table className="w-full text-left text-sm">
          <thead className="text-xs uppercase tracking-wide text-fg-subtle">
            <tr>
              <th className="px-4 py-2 font-medium">Shot</th>
              <th className="px-4 py-2 font-medium">Prompt</th>
              <th className="px-4 py-2 text-right font-medium">Time</th>
              <th className="px-4 py-2 text-right font-medium">Cost</th>
              <th className="px-4 py-2 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {shots.map((shot, index) => {
              const planned = byNode.get(shot.node_id);
              const heading = planned ? headingOf.get(planned.scene_id) : undefined;
              return (
                <tr key={shot.node_id} className="border-t align-top">
                  <td className="px-4 py-3">
                    <div className="flex items-baseline gap-2">
                      <span className="tabular-nums text-xs text-fg-subtle">
                        {String(index + 1).padStart(2, "0")}
                      </span>
                      <span className="font-mono text-xs text-fg-muted">{shot.node_id}</span>
                    </div>
                    {planned?.shot_type && (
                      <span className="mt-1.5 inline-block rounded-full border bg-surface-overlay px-2 py-0.5 text-xs text-fg-muted">
                        {planned.shot_type}
                      </span>
                    )}
                    {heading && <div className="mt-1 text-xs text-fg-subtle">{heading}</div>}
                  </td>
                  <td className="max-w-md px-4 py-3">
                    {shot.prompt ? <Prompt text={shot.prompt} /> : <span className="text-fg-subtle">-</span>}
                    {planned?.action && (
                      <div className="mt-1.5 text-xs text-fg-subtle">Action: {planned.action}</div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Timing shot={shot} entry={timeline.get(shot.node_id)} />
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Cost shot={shot} />
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={shot.status ?? "pending"} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Panel>

      {refs.length > 0 && (
        <Panel title={`Reference images (${refs.length})`}>
          <table className="w-full text-left text-sm">
            <tbody>
              {refs.map((ref) => (
                <tr key={ref.node_id} className="border-t align-top first:border-t-0">
                  <td className="w-48 px-4 py-3 font-mono text-xs text-fg-muted">{ref.node_id}</td>
                  <td className="px-4 py-3">
                    {ref.prompt ? <Prompt text={ref.prompt} /> : <span className="text-fg-subtle">-</span>}
                  </td>
                  <td className="w-24 px-4 py-3 text-right tabular-nums">
                    {formatUsd(ref.actual_cost_usd ?? ref.estimated_cost_usd ?? 0)}
                  </td>
                  <td className="w-36 px-4 py-3">
                    <StatusBadge status={ref.status ?? "pending"} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      )}
    </div>
  );
}
