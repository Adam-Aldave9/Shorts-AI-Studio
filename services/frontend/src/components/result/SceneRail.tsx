// Rows are memoized, so they take only plain values — never a scene object rebuilt on every
// filter keystroke.

import { memo, useEffect, useRef } from "react";
import { cn } from "@/components/ui";

const SceneRow = memo(function SceneRow({
  sceneId,
  position,
  heading,
  timeLabel,
  shotCount,
  narration,
  selected,
  onSelect,
}: {
  sceneId: string;
  position: number;
  heading: string;
  timeLabel: string;
  shotCount: number;
  narration: string;
  selected: boolean;
  onSelect: (sceneId: string) => void;
}) {
  return (
    <button
      type="button"
      role="option"
      aria-selected={selected}
      data-scene-id={sceneId}
      tabIndex={selected ? 0 : -1}
      onClick={() => onSelect(sceneId)}
      className={cn(
        "block w-full border-b border-b-border border-l-2 px-3 py-2 text-left transition",
        "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-accent",
        selected
          ? "border-l-accent bg-surface-overlay"
          : "border-l-transparent hover:bg-surface-overlay/50",
      )}
    >
      <div className="flex items-baseline gap-2">
        <span className="tabular-nums text-xs text-fg-subtle">
          {String(position).padStart(2, "0")}
        </span>
        <span className="truncate text-sm font-medium text-fg">{heading}</span>
      </div>
      <div className="mt-0.5 pl-6 text-xs tabular-nums text-fg-subtle">
        {timeLabel} · {shotCount} {shotCount === 1 ? "shot" : "shots"}
      </div>
      <div className="mt-1 line-clamp-2 pl-6 text-xs leading-relaxed text-fg-muted">
        {narration || "-"}
      </div>
    </button>
  );
});

export interface SceneRailItem {
  id: string;
  heading: string;
  timeLabel: string;
  shotCount: number;
  narration: string;
}

export function SceneRail({
  scenes,
  selectedId,
  onSelect,
  onMove,
}: {
  scenes: SceneRailItem[];
  selectedId: string | null;
  onSelect: (sceneId: string) => void;
  /** -1 / +1 from the arrow keys; the browser owns the clamping. */
  onMove: (delta: number) => void;
}) {
  const listRef = useRef<HTMLDivElement>(null);

  // Focus follows the selection only while the keyboard is driving the rail, so the pager in
  // the detail pane can change scenes without stealing focus.
  useEffect(() => {
    const list = listRef.current;
    if (!list || selectedId == null) return;
    const row = list.querySelector<HTMLButtonElement>(
      `[data-scene-id="${CSS.escape(selectedId)}"]`,
    );
    if (!row) return;
    row.scrollIntoView({ block: "nearest" });
    if (list.contains(document.activeElement) && document.activeElement !== row) row.focus();
  }, [selectedId]);

  return (
    <div
      ref={listRef}
      role="listbox"
      aria-label="Scenes"
      tabIndex={-1}
      className="min-h-0 overflow-y-auto rounded-xl border bg-surface-raised"
      onKeyDown={(event) => {
        if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
        event.preventDefault();
        onMove(event.key === "ArrowDown" ? 1 : -1);
      }}
    >
      {scenes.map((scene, index) => (
        <SceneRow
          key={scene.id}
          sceneId={scene.id}
          position={index + 1}
          heading={scene.heading}
          timeLabel={scene.timeLabel}
          shotCount={scene.shotCount}
          narration={scene.narration}
          selected={scene.id === selectedId}
          onSelect={onSelect}
        />
      ))}
    </div>
  );
}
