// A film is every version sharing one `film_id`; these helpers turn the flat run list into
// films and route each version to the screen for its phase.

import type { PackageSummary, ReusePlan } from "@/api/client";
import { formatUsd } from "@/lib/format";

const RUNNING_PHASES = new Set(["executing", "compositing", "blocked", "paused"]);

export function destination(run: { project_id: string; phase: string | null }): string {
  if (run.phase === "complete") return `/result/${run.project_id}`;
  if (run.phase && RUNNING_PHASES.has(run.phase)) return `/status/${run.project_id}`;
  return `/checkpoint/${run.project_id}`;
}

interface Film {
  filmId: string;
  /** Oldest first. */
  versions: PackageSummary[];
  latest: PackageSummary;
  totalCostUsd: number;
  /** ISO timestamp of the newest version. */
  lastActivity: string;
}

export function groupByFilm(rows: PackageSummary[]): Film[] {
  const byFilm = new Map<string, PackageSummary[]>();
  for (const row of rows) {
    const bucket = byFilm.get(row.film_id);
    if (bucket) bucket.push(row);
    else byFilm.set(row.film_id, [row]);
  }
  const films = [...byFilm.entries()].map(([filmId, versions]) => {
    versions.sort((a, b) => a.version - b.version || a.created_at.localeCompare(b.created_at));
    const latest = versions[versions.length - 1];
    const lastActivity = versions.reduce(
      (newest, v) => (v.created_at > newest ? v.created_at : newest),
      latest.created_at,
    );
    return {
      filmId,
      versions,
      latest,
      totalCostUsd: versions.reduce((sum, v) => sum + v.cost_usd, 0),
      lastActivity,
    };
  });
  return films.sort((a, b) => b.lastActivity.localeCompare(a.lastActivity));
}

export function reuseSummary(plan: ReusePlan, totalAssets: number): string {
  const reused = Object.keys(plan.nodes).length;
  return `${reused} of ${totalAssets} assets reused from earlier versions - about ${formatUsd(plan.render_cost_usd)} to render`;
}
