// Rows are memoized, so they must receive only plain values — never `nodeValue`/`isNodeDirty`,
// which close over the draft and get a fresh identity on every keystroke.

import { memo, useEffect, useRef } from "react";
import type { Asset } from "@/api/client";
import { shotDurationS } from "@/lib/package";
import { formatDuration, formatUsd } from "@/lib/format";
import { cn } from "@/components/ui";

const ShotRow = memo(function ShotRow({
  asset,
  index,
  prompt,
  selected,
  edited,
  onSelect,
}: {
  asset: Asset;
  index: number;
  prompt: string;
  selected: boolean;
  edited: boolean;
  onSelect: (nodeId: string) => void;
}) {
  return (
    <button
      type="button"
      role="option"
      aria-selected={selected}
      data-node-id={asset.node_id}
      tabIndex={selected ? 0 : -1}
      onClick={() => onSelect(asset.node_id)}
      className={cn(
        "block w-full border-l-2 border-b border-b-border px-3 py-2 text-left transition",
        "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-accent",
        selected
          ? "border-l-accent bg-surface-overlay"
          : "border-l-transparent hover:bg-surface-overlay/50",
      )}
    >
      <div className="flex items-center gap-2">
        <span className="tabular-nums text-xs text-fg-subtle">
          {String(index + 1).padStart(2, "0")}
        </span>
        <span className="truncate font-mono text-xs text-fg-muted">{asset.node_id}</span>
        {edited && (
          <span
            className="ml-auto h-1.5 w-1.5 shrink-0 rounded-full bg-accent"
            title="Edited"
            aria-label="Edited"
          />
        )}
      </div>
      <div className="mt-1 line-clamp-2 text-sm text-fg-muted">{prompt || "-"}</div>
      <div className="mt-1 text-xs tabular-nums text-fg-subtle">
        {formatDuration(shotDurationS(asset))} · {formatUsd(asset.estimated_cost_usd ?? 0)}
      </div>
    </button>
  );
});

export function ShotRail({
  assets,
  selectedNodeId,
  valueOf,
  isEdited,
  onSelect,
  onMove,
}: {
  assets: Asset[];
  selectedNodeId: string | null;
  valueOf: (nodeId: string) => string;
  isEdited: (nodeId: string) => boolean;
  onSelect: (nodeId: string) => void;
  /** -1 / +1 from the arrow keys; the workbench owns the clamping. */
  onMove: (delta: number) => void;
}) {
  const listRef = useRef<HTMLDivElement>(null);

  // Focus follows the selection only when the keyboard is already driving the rail: clicking
  // a reference chip in the detail pane also changes the selection, and must not steal focus.
  useEffect(() => {
    const list = listRef.current;
    if (!list || !selectedNodeId) return;
    const row = list.querySelector<HTMLButtonElement>(
      `[data-node-id="${CSS.escape(selectedNodeId)}"]`,
    );
    if (!row) return;
    row.scrollIntoView({ block: "nearest" });
    if (list.contains(document.activeElement) && document.activeElement !== row) row.focus();
  }, [selectedNodeId]);

  return (
    <div
      ref={listRef}
      role="listbox"
      aria-label="Assets"
      tabIndex={-1}
      className="min-h-0 overflow-y-auto rounded-xl border bg-surface-raised"
      onKeyDown={(event) => {
        if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
        event.preventDefault();
        onMove(event.key === "ArrowDown" ? 1 : -1);
      }}
    >
      {assets.map((asset, index) => (
        <ShotRow
          key={asset.node_id}
          asset={asset}
          index={index}
          prompt={valueOf(asset.node_id)}
          selected={asset.node_id === selectedNodeId}
          edited={isEdited(asset.node_id)}
          onSelect={onSelect}
        />
      ))}
    </div>
  );
}
