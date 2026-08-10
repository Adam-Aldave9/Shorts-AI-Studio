// Master-detail shell for the script: a filterable rail of scenes beside one focused scene.
// Fixed-height so a 9-scene short and a 90-scene feature take the same room on the page.

import { useCallback, useMemo, useState } from "react";
import type { ProductionPackage } from "@/api/client";
import {
  scenes as narrativeScenes,
  sceneSpans,
  scriptDiverged,
  shotsByScene,
  voiceovers,
} from "@/lib/package";
import { formatTimecode } from "@/lib/format";
import { Card, EmptyState, WarningBanner, controlClass } from "@/components/ui";
import { SceneRail, type SceneRailItem } from "./SceneRail";
import { SceneDetail, type SceneView } from "./SceneDetail";

const UNSCENED = "";

function useSceneViews(pkg: ProductionPackage): SceneView[] {
  return useMemo(() => {
    const byScene = shotsByScene(pkg);
    const spans = sceneSpans(pkg);
    // `location` / `beat` / `narration` carry Pydantic defaults, so they arrive optional.
    const views: SceneView[] = narrativeScenes(pkg).map((scene) => ({
      id: scene.id,
      heading: scene.heading,
      location: scene.location ?? "",
      beat: scene.beat ?? "",
      narration: scene.narration ?? "",
      shots: byScene.get(scene.id) ?? [],
      span: spans.get(scene.id) ?? null,
    }));

    // Shots the narrative never claimed still have to be reachable.
    const orphans = byScene.get(UNSCENED) ?? [];
    if (orphans.length > 0) {
      views.push({
        id: UNSCENED,
        heading: "Not in any scene",
        location: "",
        beat: "",
        narration: "",
        shots: orphans,
        span: spans.get(UNSCENED) ?? null,
      });
    }
    return views;
  }, [pkg]);
}

function matches(scene: SceneView, needle: string): boolean {
  return (
    scene.heading.toLowerCase().includes(needle) ||
    scene.location.toLowerCase().includes(needle) ||
    scene.beat.toLowerCase().includes(needle) ||
    scene.narration.toLowerCase().includes(needle) ||
    scene.shots.some((shot) => shot.node_id.toLowerCase().includes(needle))
  );
}

/** Packages planned before schema 1.1 have no scenes, only the flattened voiceover blob. */
function FlatScript({ pkg }: { pkg: ProductionPackage }) {
  const narration = voiceovers(pkg)
    .map((asset) => asset.text ?? "")
    .filter(Boolean);

  if (narration.length === 0) {
    return (
      <EmptyState title="No script recorded">
        This package carries no narration or scene breakdown.
      </EmptyState>
    );
  }
  return (
    <div className="space-y-3">
      <p className="text-xs text-fg-subtle">
        This package was planned before scene-level detail was recorded, so the narration is
        shown as one block.
      </p>
      <div className="max-h-[50vh] space-y-3 overflow-y-auto">
        {narration.map((text, index) => (
          <blockquote
            key={index}
            className="border-l-2 border-border-strong pl-4 text-sm leading-relaxed text-fg-muted"
          >
            {text}
          </blockquote>
        ))}
      </div>
    </div>
  );
}

export function SceneBrowser({
  pkg,
  onSeek,
}: {
  pkg: ProductionPackage;
  onSeek: (nodeId: string) => void;
}) {
  const views = useSceneViews(pkg);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  const needle = filter.trim().toLowerCase();
  const visible = needle ? views.filter((scene) => matches(scene, needle)) : views;

  // Derived, not synced in an effect, so a filter that excludes the selection falls back to
  // the first match on its own.
  const active = visible.find((scene) => scene.id === selectedId) ?? visible[0] ?? null;
  const position = active ? visible.indexOf(active) + 1 : 0;

  const onSelect = useCallback((sceneId: string) => setSelectedId(sceneId), []);

  const onMove = useCallback(
    (delta: number) => {
      if (!active) return;
      const next = visible[visible.indexOf(active) + delta];
      if (next) setSelectedId(next.id);
    },
    [active, visible],
  );

  const railItems: SceneRailItem[] = visible.map((scene) => ({
    id: scene.id,
    heading: scene.heading,
    timeLabel: scene.span
      ? `${formatTimecode(scene.span.in_s)}-${formatTimecode(scene.span.out_s)}`
      : "-",
    shotCount: scene.shots.length,
    narration: scene.narration,
  }));

  return (
    <Card className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="text-xs uppercase tracking-wide text-fg-subtle">Script</div>
        {views.length > 0 && (
          <input
            className={`${controlClass} ml-auto max-w-xs flex-1`}
            type="search"
            placeholder="Search scenes..."
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            aria-label="Filter scenes by heading, narration or shot id"
          />
        )}
        <span className="tabular-nums text-xs text-fg-subtle">
          {views.length > 0 ? `${views.length} scenes` : null}
        </span>
      </div>

      {scriptDiverged(pkg) && (
        <WarningBanner className="px-3 py-2 text-xs">
          The narration was edited at the checkpoint after planning — the scenes below are the
          original draft, not what was spoken in the final cut.
        </WarningBanner>
      )}

      {views.length === 0 ? (
        <FlatScript pkg={pkg} />
      ) : (
        <div className="grid h-[32rem] grid-cols-1 grid-rows-[11rem_minmax(0,1fr)] gap-3 lg:h-[26rem] lg:grid-cols-[minmax(220px,280px)_minmax(0,1fr)] lg:grid-rows-1">
          <SceneRail
            scenes={railItems}
            selectedId={active?.id ?? null}
            onSelect={onSelect}
            onMove={onMove}
          />
          {active ? (
            <SceneDetail
              key={active.id}
              scene={active}
              position={position}
              total={visible.length}
              onMove={onMove}
              onSeek={onSeek}
            />
          ) : (
            <EmptyState title="No matches">
              No scene matches &ldquo;{filter}&rdquo;.
            </EmptyState>
          )}
        </div>
      )}
    </Card>
  );
}
