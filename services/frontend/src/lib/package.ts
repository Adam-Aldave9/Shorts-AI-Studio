import type {
  Asset,
  NarrativeScene,
  NarrativeShot,
  ProductionPackage,
  TimelineEntry,
} from "@/api/client";

function assetsByType(pkg: ProductionPackage, type: Asset["type"]): Asset[] {
  return (pkg.assets ?? []).filter((asset) => asset.type === type);
}

export const videoShots = (pkg: ProductionPackage): Asset[] => assetsByType(pkg, "video");
export const voiceovers = (pkg: ProductionPackage): Asset[] => assetsByType(pkg, "voiceover");
export const referenceImages = (pkg: ProductionPackage): Asset[] => assetsByType(pkg, "image");

/** A shot's duration lives in its free-form `spec` (the validator reads `duration_s`). */
export function shotDurationS(asset: Asset): number {
  const raw = asset.spec?.["duration_s"];
  const value = typeof raw === "number" ? raw : Number(raw);
  return Number.isFinite(value) ? value : 0;
}

export function estimatedTotalUsd(pkg: ProductionPackage): number {
  return (pkg.assets ?? []).reduce((sum, asset) => sum + (asset.estimated_cost_usd ?? 0), 0);
}

export function actualTotalUsd(pkg: ProductionPackage): number {
  return (pkg.assets ?? []).reduce((sum, asset) => sum + (asset.actual_cost_usd ?? 0), 0);
}

// ---------------------------------------------------------------------------
// The narrative block (schema 1.1). `pkg.narrative` is null on older packages, so
// every reader here degrades to an empty map rather than throwing.
// ---------------------------------------------------------------------------

export const scenes = (pkg: ProductionPackage): NarrativeScene[] => pkg.narrative?.scenes ?? [];

export function narrativeShotByNode(pkg: ProductionPackage): Map<string, NarrativeShot> {
  return new Map((pkg.narrative?.shots ?? []).map((shot) => [shot.node_id, shot]));
}

export function timelineByNode(pkg: ProductionPackage): Map<string, TimelineEntry> {
  return new Map((pkg.timeline ?? []).map((entry) => [entry.node_id, entry]));
}

/** Video assets in timeline order; anything absent from the timeline keeps package order
 *  at the end rather than disappearing. */
export function shotsInPlaybackOrder(pkg: ProductionPackage): Asset[] {
  const timeline = timelineByNode(pkg);
  // MAX_SAFE_INTEGER rather than Infinity: subtracting two Infinities yields NaN and
  // silently corrupts the sort.
  const startOf = (asset: Asset) =>
    timeline.get(asset.node_id)?.in_s ?? Number.MAX_SAFE_INTEGER;
  return videoShots(pkg)
    .map((asset, index) => ({ asset, index }))
    .sort((a, b) => startOf(a.asset) - startOf(b.asset) || a.index - b.index)
    .map((entry) => entry.asset);
}

/** scene_id -> its shots, in playback order. Shots with no narrative entry collect under
 *  `""`, which the UI renders last as "unscened". */
export function shotsByScene(pkg: ProductionPackage): Map<string, Asset[]> {
  const byNode = narrativeShotByNode(pkg);
  const grouped = new Map<string, Asset[]>();
  for (const asset of shotsInPlaybackOrder(pkg)) {
    const sceneId = byNode.get(asset.node_id)?.scene_id ?? "";
    const bucket = grouped.get(sceneId);
    if (bucket) bucket.push(asset);
    else grouped.set(sceneId, [asset]);
  }
  return grouped;
}

/** Where each scene lands in the final cut: its first shot's in point to its last shot's out
 *  point. Scenes whose shots are absent from the timeline are omitted rather than zeroed. */
export function sceneSpans(pkg: ProductionPackage): Map<string, { in_s: number; out_s: number }> {
  const timeline = timelineByNode(pkg);
  const spans = new Map<string, { in_s: number; out_s: number }>();
  for (const [sceneId, shots] of shotsByScene(pkg)) {
    const entries = shots
      .map((shot) => timeline.get(shot.node_id))
      .filter((entry): entry is TimelineEntry => entry != null);
    if (entries.length === 0) continue;
    spans.set(sceneId, {
      in_s: Math.min(...entries.map((entry) => entry.in_s)),
      out_s: Math.max(...entries.map((entry) => entry.out_s)),
    });
  }
  return spans;
}

const normalized = (text: string): string => text.replace(/\s+/g, " ").trim();

/** True when the narration was edited at the checkpoint after planning, so the scene-level
 *  script on screen is no longer what was actually spoken. Assembly builds the voiceover
 *  blob by joining the scene narration, so equality is the untouched case. */
export function scriptDiverged(pkg: ProductionPackage): boolean {
  const sceneList = scenes(pkg);
  if (sceneList.length === 0) return false;
  const spoken = voiceovers(pkg)
    .map((asset) => asset.text ?? "")
    .join(" ");
  return normalized(spoken) !== normalized(sceneList.map((scene) => scene.narration).join(" "));
}
