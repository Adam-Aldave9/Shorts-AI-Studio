// What a revision changed from its parent, what it reused, and what it cost.

import type { Lineage, ReusePlan, VersionSummary } from "@/api/client";
import { reuseSummary } from "@/lib/films";
import { formatUsd } from "@/lib/format";
import { Button, Card } from "@/components/ui";

const STAGE_LABELS: Record<string, string> = {
  brief: "the brief",
  world: "the world",
  script: "the script",
  shots: "the shots",
};

export function WhatChanged({
  lineage,
  reuse,
  totalAssets,
  versions,
  projectId,
  onCompare,
}: {
  lineage: Lineage;
  reuse: ReusePlan | undefined;
  totalAssets: number;
  versions: VersionSummary[];
  projectId: string;
  onCompare: (() => void) | null;
}) {
  const parent = versions.find((v) => v.project_id === lineage.parent_project_id);
  const own = versions.find((v) => v.project_id === projectId);
  const filmTotal = versions.reduce((sum, v) => sum + v.cost_usd, 0);
  const changes = lineage.changes ?? [];

  return (
    <Card className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold">What changed</h2>
          <p className="text-xs text-fg-subtle">
            Revised from {parent ? `v${parent.version}` : "an earlier version"}
            {lineage.from_stage &&
              `, starting at ${STAGE_LABELS[lineage.from_stage] ?? lineage.from_stage}`}
          </p>
        </div>
        {onCompare && parent && (
          <Button variant="secondary" onClick={onCompare}>
            Compare with v{parent.version}
          </Button>
        )}
      </div>
      {lineage.note && <p className="text-sm italic text-fg-muted">&ldquo;{lineage.note}&rdquo;</p>}
      {changes.length > 0 ? (
        <ul className="list-disc space-y-0.5 pl-5 text-sm text-fg-muted">
          {changes.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-fg-muted">No story changes - a re-render of the same cut.</p>
      )}
      <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-border pt-3 text-xs text-fg-subtle">
        {reuse && <span>{reuseSummary(reuse, totalAssets)}</span>}
        {own && (
          <span className="tabular-nums">
            This version cost {formatUsd(own.cost_usd)} - film total {formatUsd(filmTotal)}
          </span>
        )}
      </div>
    </Card>
  );
}
