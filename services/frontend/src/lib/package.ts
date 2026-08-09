import type { Asset, ProductionPackage } from "@/api/client";

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
