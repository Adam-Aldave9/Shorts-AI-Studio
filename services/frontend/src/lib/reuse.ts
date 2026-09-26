// Checkpoint view of a revision's reuse plan, adjusted for what the user is doing right now:
// an edited node renders fresh, and "Re-render anyway" on an image also re-renders every
// shot animated from it (the start frame is part of a shot's render fingerprint).

import type { Asset, ReusePlan } from "@/api/client";

export interface NodeReuse {
  /** "v1" - the version whose render is reused. */
  source: string;
  rerender: boolean;
  /** The start-frame image whose re-render forces this shot to render too. */
  forcedBy: string | null;
}

export function nodeReuse(
  assets: Asset[],
  plan: ReusePlan | undefined,
  rerender: ReadonlySet<string>,
  isDirty: (nodeId: string) => boolean,
): Map<string, NodeReuse> {
  const out = new Map<string, NodeReuse>();
  if (!plan) return out;
  for (const asset of assets) {
    const source = plan.nodes[asset.node_id];
    if (!source || isDirty(asset.node_id)) continue;
    const start = asset.type === "video" ? asset.reference_image_ids?.[0] : undefined;
    out.set(asset.node_id, {
      source: `v${source.source_version}`,
      rerender: rerender.has(asset.node_id),
      forcedBy: start && (rerender.has(start) || isDirty(start)) ? start : null,
    });
  }
  return out;
}

export function isReused(reuse: NodeReuse | undefined): boolean {
  return reuse !== undefined && !reuse.rerender && reuse.forcedBy === null;
}

/** The reused shots animated from `imageId`, which re-render with it. */
export function cascadeOf(
  assets: Asset[],
  imageId: string,
  reuse: Map<string, NodeReuse>,
): string[] {
  return assets
    .filter((a) => a.type === "video" && a.reference_image_ids?.[0] === imageId)
    .filter((a) => reuse.has(a.node_id) && !reuse.get(a.node_id)!.rerender)
    .map((a) => a.node_id);
}

export function renderCostUsd(assets: Asset[], reuse: Map<string, NodeReuse>): number {
  return assets
    .filter((a) => !isReused(reuse.get(a.node_id)))
    .reduce((sum, a) => sum + (a.estimated_cost_usd ?? 0), 0);
}
