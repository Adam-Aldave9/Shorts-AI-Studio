// The editable projection of a production package: the fields a human may change at the
// checkpoint, read out of a package and folded back in.
//
// The invariant that makes structured editing safe: a merge only ever writes meta scalars and
// prompt/text strings. It never touches `node_id`, `type`, `depends_on`, `spec`,
// `reference_image_ids`, costs or `status`, so folding a draft back cannot corrupt the DAG.

import type { ProductionPackage } from "@/api/client";

/** `budget_usd` is a string so the number input can hold intermediate states ("", "3."). */
interface DraftMeta {
  title: string;
  premise: string;
  style: string;
  aspect_ratio: string;
  narration_voice_id: string;
  budget_usd: string;
}

export type DraftMetaKey = keyof DraftMeta;

const META_KEYS: readonly DraftMetaKey[] = [
  "title",
  "premise",
  "style",
  "aspect_ratio",
  "narration_voice_id",
  "budget_usd",
];

export interface PackageDraft {
  meta: DraftMeta;
  /** node_id -> the node's one editable string: `prompt` for video/image, `text` for
   *  voiceover. Flat because node ids are unique across the DAG. */
  nodes: Record<string, string>;
}

export function draftFromPackage(pkg: ProductionPackage): PackageDraft {
  const nodes: Record<string, string> = {};
  for (const asset of pkg.assets ?? []) {
    if (asset.type === "video" || asset.type === "image") nodes[asset.node_id] = asset.prompt ?? "";
    else if (asset.type === "voiceover") nodes[asset.node_id] = asset.text ?? "";
  }
  return {
    meta: {
      title: pkg.meta.title,
      premise: pkg.meta.premise,
      style: pkg.meta.style,
      aspect_ratio: pkg.meta.aspect_ratio ?? "16:9",
      narration_voice_id: pkg.meta.narration_voice_id,
      budget_usd: String(pkg.meta.budget_usd),
    },
    nodes,
  };
}

/** A cleared or malformed budget field would serialize as `null` and earn an opaque 422, so
 *  fall back until the input parses again. */
function budgetOrFallback(raw: string, fallback: number): number {
  const value = Number(raw);
  return Number.isFinite(value) ? value : fallback;
}

export function mergeDraft(pkg: ProductionPackage, draft: PackageDraft): ProductionPackage {
  return {
    ...pkg,
    meta: {
      ...pkg.meta,
      ...draft.meta,
      budget_usd: budgetOrFallback(draft.meta.budget_usd, pkg.meta.budget_usd),
    },
    assets: (pkg.assets ?? []).map((asset) => {
      // Unknown keys stay inert so a draft outliving a structural JSON edit (a node renamed
      // or removed) cannot resurrect the node.
      if (!(asset.node_id in draft.nodes)) return asset;
      if (asset.type === "video" || asset.type === "image") {
        return { ...asset, prompt: draft.nodes[asset.node_id] };
      }
      if (asset.type === "voiceover") return { ...asset, text: draft.nodes[asset.node_id] };
      return asset;
    }),
  };
}

/** Field-wise rather than a `JSON.stringify` pair, which would re-serialize the whole package
 *  on every keystroke. */
export function draftEquals(a: PackageDraft, b: PackageDraft): boolean {
  if (a === b) return true;
  for (const key of META_KEYS) {
    if (a.meta[key] !== b.meta[key]) return false;
  }
  const keys = Object.keys(a.nodes);
  if (keys.length !== Object.keys(b.nodes).length) return false;
  for (const key of keys) {
    if (a.nodes[key] !== b.nodes[key]) return false;
  }
  return true;
}
