// Master-detail shell for the Shots tab: a filterable rail of assets beside one focused editor.

import { useCallback, useMemo, useState } from "react";
import type { Asset, ProductionPackage } from "@/api/client";
import type { PackageDraftApi } from "@/hooks/usePackageDraft";
import { referenceImages, videoShots } from "@/lib/package";
import { EmptyState, Tabs, controlClass } from "@/components/ui";
import { ShotRail } from "./ShotRail";
import { ShotDetail } from "./ShotDetail";

type AssetKind = "video" | "image";

/** node_id of a reference image -> the shots that consume it; the package only stores
 *  `reference_image_ids` in the forward direction. */
function buildUsedBy(pkg: ProductionPackage): Record<string, string[]> {
  const index: Record<string, string[]> = {};
  for (const asset of pkg.assets ?? []) {
    for (const refId of asset.reference_image_ids ?? []) {
      (index[refId] ??= []).push(asset.node_id);
    }
  }
  return index;
}

function matches(asset: Asset, needle: string, prompt: string): boolean {
  return asset.node_id.toLowerCase().includes(needle) || prompt.toLowerCase().includes(needle);
}

export function ShotWorkbench({
  pkg,
  nodeValue,
  setNode,
  isNodeDirty,
  resetNode,
  readOnly,
}: Pick<PackageDraftApi, "nodeValue" | "setNode" | "isNodeDirty" | "resetNode"> & {
  pkg: ProductionPackage;
  readOnly: boolean;
}) {
  const [kind, setKind] = useState<AssetKind>("video");
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  // From `pkg`, not `merged`: `merged` allocates fresh asset objects on every keystroke,
  // which would kill the rail rows' memo.
  const videos = useMemo(() => videoShots(pkg), [pkg]);
  const images = useMemo(() => referenceImages(pkg), [pkg]);
  const usedBy = useMemo(() => buildUsedBy(pkg), [pkg]);

  const assets = kind === "video" ? videos : images;
  const needle = filter.trim().toLowerCase();
  const visible = needle
    ? assets.filter((asset) => matches(asset, needle, nodeValue(asset.node_id)))
    : assets;

  // Derived, not synced in an effect, so a filter that excludes the selection falls back to
  // the first match on its own.
  const active = visible.find((asset) => asset.node_id === selectedNodeId) ?? visible[0] ?? null;
  const position = active ? visible.indexOf(active) + 1 : 0;

  const onSelect = useCallback((nodeId: string) => setSelectedNodeId(nodeId), []);

  const onMove = useCallback(
    (delta: number) => {
      if (!active) return;
      const next = visible[visible.indexOf(active) + delta];
      if (next) setSelectedNodeId(next.node_id);
    },
    [active, visible],
  );

  const onOpenNode = useCallback(
    (nodeId: string) => {
      const target = (pkg.assets ?? []).find((asset) => asset.node_id === nodeId);
      if (!target || (target.type !== "video" && target.type !== "image")) return;
      setKind(target.type);
      setFilter("");
      setSelectedNodeId(nodeId);
    },
    [pkg],
  );

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <input
          className={`${controlClass} max-w-xs flex-1`}
          type="search"
          placeholder="Search shots..."
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          aria-label="Filter assets by id or prompt"
        />
        <Tabs
          className="ml-auto"
          tabs={[
            { id: "video" as const, label: "Video", badge: videos.length },
            { id: "image" as const, label: "Refs", badge: images.length },
          ]}
          active={kind}
          onChange={setKind}
        />
      </div>

      {assets.length === 0 ? (
        <EmptyState title={kind === "video" ? "No video shots" : "No reference images"}>
          This package has no {kind === "video" ? "video shots" : "reference images"} to edit.
        </EmptyState>
      ) : (
        <div className="grid h-[70vh] grid-cols-1 grid-rows-[16rem_minmax(0,1fr)] gap-4 lg:grid-cols-[minmax(240px,300px)_minmax(0,1fr)] lg:grid-rows-1">
          <ShotRail
            assets={visible}
            selectedNodeId={active?.node_id ?? null}
            valueOf={nodeValue}
            isEdited={isNodeDirty}
            onSelect={onSelect}
            onMove={onMove}
          />
          {active ? (
            <ShotDetail
              key={active.node_id}
              asset={active}
              position={position}
              total={visible.length}
              value={nodeValue(active.node_id)}
              edited={isNodeDirty(active.node_id)}
              readOnly={readOnly}
              usedBy={usedBy[active.node_id] ?? []}
              onChange={(value) => setNode(active.node_id, value)}
              onReset={() => resetNode(active.node_id)}
              onMove={onMove}
              onOpenNode={onOpenNode}
            />
          ) : (
            <EmptyState title="No matches">
              Nothing in this list matches &ldquo;{filter}&rdquo;.
            </EmptyState>
          )}
        </div>
      )}
    </div>
  );
}
