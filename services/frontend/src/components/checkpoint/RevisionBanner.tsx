// Shown on a revision's checkpoint: where it came from, what changed, and how much it reuses.

import { Link } from "react-router-dom";
import type { Lineage, VersionSummary } from "@/api/client";
import { destination } from "@/lib/films";
import { formatUsd } from "@/lib/format";

export function RevisionBanner({
  lineage,
  versions,
  reusedCount,
  totalAssets,
  renderCostUsd,
}: {
  lineage: Lineage;
  versions: VersionSummary[];
  reusedCount: number | null;
  totalAssets: number;
  renderCostUsd: number | null;
}) {
  const parent = versions.find((v) => v.project_id === lineage.parent_project_id);
  const changes = lineage.changes ?? [];
  return (
    <div className="rounded-md border border-accent/30 bg-accent/10 px-4 py-3 text-sm">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="font-medium text-fg">
          Revision v{lineage.version ?? 1}
          {parent && ` (from v${parent.version})`}
        </div>
        {parent && (
          <Link
            className="text-xs text-accent-soft underline hover:text-accent"
            to={destination(parent)}
          >
            Open v{parent.version}
          </Link>
        )}
      </div>
      {lineage.note && <p className="mt-1 italic text-fg-muted">&ldquo;{lineage.note}&rdquo;</p>}
      {reusedCount !== null && renderCostUsd !== null && (
        <p className="mt-1 text-fg-muted">
          {reusedCount} of {totalAssets} assets reused from earlier versions - about{" "}
          {formatUsd(renderCostUsd)} to render
        </p>
      )}
      {changes.length > 0 && (
        <details className="mt-1 text-fg-muted">
          <summary className="cursor-pointer select-none text-xs hover:text-fg">
            {changes.length} {changes.length === 1 ? "change" : "changes"}
          </summary>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs">
            {changes.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
