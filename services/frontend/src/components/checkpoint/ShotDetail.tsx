// One asset, edited at full size, with its DAG edges in the footer.

import type { Asset } from "@/api/client";
import { shotDurationS } from "@/lib/package";
import type { NodeReuse } from "@/lib/reuse";
import { formatDuration, formatUsd } from "@/lib/format";
import { Button, PromptBudget, cn } from "@/components/ui";

function MetaChip({ children }: { children: string }) {
  return (
    <span className="rounded border border-border bg-surface px-1.5 py-0.5 font-mono text-[11px] text-fg-muted">
      {children}
    </span>
  );
}

function NodeLink({ nodeId, onOpen }: { nodeId: string; onOpen: (nodeId: string) => void }) {
  return (
    <button
      type="button"
      onClick={() => onOpen(nodeId)}
      className={cn(
        "rounded border border-border bg-surface px-1.5 py-0.5 font-mono text-[11px] text-accent-soft transition",
        "hover:border-border-strong hover:text-accent",
        "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent",
      )}
    >
      {nodeId}
    </button>
  );
}

export function RerenderToggle({
  reuse,
  cascade = [],
  readOnly,
  onToggle,
  onOpenNode,
}: {
  reuse: NodeReuse;
  cascade?: string[];
  readOnly: boolean;
  onToggle: () => void;
  onOpenNode?: (nodeId: string) => void;
}) {
  if (reuse.forcedBy) {
    return (
      <p className="text-xs text-fg-subtle">
        Renders again because its start frame {reuse.forcedBy} re-renders.
      </p>
    );
  }
  return (
    <div className="rounded-md border border-accent/30 bg-accent/10 px-3 py-2 text-xs">
      <label className="flex items-center gap-2 text-fg">
        <input type="checkbox" checked={reuse.rerender} disabled={readOnly} onChange={onToggle} />
        Re-render anyway
        <span className="text-fg-subtle">
          {reuse.rerender
            ? "- a fresh take renders at approve"
            : `- otherwise the ${reuse.source} render is reused for $0`}
        </span>
      </label>
      {cascade.length > 0 && (
        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-fg-subtle">
          Also re-renders
          {cascade.map((nodeId) =>
            onOpenNode ? (
              <NodeLink key={nodeId} nodeId={nodeId} onOpen={onOpenNode} />
            ) : (
              <span key={nodeId} className="font-mono">
                {nodeId}
              </span>
            ),
          )}
        </div>
      )}
    </div>
  );
}

export function ShotDetail({
  asset,
  position,
  total,
  value,
  edited,
  readOnly,
  usedBy,
  limit,
  onChange,
  onReset,
  onMove,
  onOpenNode,
  reuse,
  cascade,
  onToggleRerender,
}: {
  asset: Asset;
  /** 1-based index within the currently filtered list. */
  position: number;
  total: number;
  value: string;
  edited: boolean;
  readOnly: boolean;
  /** For a reference image: the shots that name it in `reference_image_ids`. */
  usedBy: string[];
  /** The provider's prompt limit in UTF-8 bytes, when it has one. */
  limit?: number;
  onChange: (value: string) => void;
  onReset: () => void;
  onMove: (delta: number) => void;
  onOpenNode: (nodeId: string) => void;
  /** Set when an earlier version already rendered exactly this node. */
  reuse: NodeReuse | null;
  /** For a reused image: the reused shots animated from it, which re-render with it. */
  cascade: string[];
  onToggleRerender: () => void;
}) {
  const isVoiceover = asset.type === "voiceover";
  const references = asset.reference_image_ids ?? [];
  const dependsOn = asset.depends_on ?? [];

  return (
    <div className="flex min-h-0 flex-col overflow-hidden rounded-xl border bg-surface-raised">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2.5">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="truncate font-mono text-sm text-fg">{asset.node_id}</span>
          {asset.provider_hint && <MetaChip>{asset.provider_hint}</MetaChip>}
          <span className="text-xs tabular-nums text-fg-subtle">
            {formatDuration(shotDurationS(asset))} · {formatUsd(asset.estimated_cost_usd ?? 0)}
          </span>
        </div>
        <div className="flex items-center gap-1 text-xs text-fg-subtle">
          <button
            type="button"
            className="rounded px-1.5 py-0.5 hover:bg-surface-overlay hover:text-fg disabled:opacity-40 disabled:hover:bg-transparent"
            onClick={() => onMove(-1)}
            disabled={position <= 1}
            aria-label="Previous"
          >
            &lt;
          </button>
          <span className="tabular-nums">
            {position} of {total}
          </span>
          <button
            type="button"
            className="rounded px-1.5 py-0.5 hover:bg-surface-overlay hover:text-fg disabled:opacity-40 disabled:hover:bg-transparent"
            onClick={() => onMove(1)}
            disabled={position >= total}
            aria-label="Next"
          >
            &gt;
          </button>
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-2 p-4">
        <div className="flex items-center justify-between">
          <label
            className="text-xs uppercase tracking-wide text-fg-subtle"
            htmlFor="shot-detail-prompt"
          >
            {isVoiceover ? "Narration" : "Prompt"}
          </label>
          {edited && !readOnly && (
            <Button variant="ghost" className="px-2 py-1 text-xs" onClick={onReset}>
              Reset {isVoiceover ? "narration" : "shot"}
            </Button>
          )}
        </div>
        <textarea
          id="shot-detail-prompt"
          className="min-h-[8rem] w-full flex-1 resize-none rounded-md border border-border bg-surface px-3 py-2 text-sm leading-relaxed text-fg placeholder:text-fg-subtle focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent disabled:opacity-60"
          value={value}
          disabled={readOnly}
          spellCheck
          onChange={(event) => onChange(event.target.value)}
        />
        <PromptBudget value={value} limit={limit} />
        {reuse && (
          <RerenderToggle
            reuse={reuse}
            cascade={cascade}
            readOnly={readOnly}
            onToggle={onToggleRerender}
            onOpenNode={onOpenNode}
          />
        )}
      </div>

      {(references.length > 0 || usedBy.length > 0 || dependsOn.length > 0) && (
        <div className="max-h-32 shrink-0 space-y-2 overflow-y-auto border-t border-border px-4 py-3 text-xs">
          {references.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-fg-subtle">Uses reference</span>
              {references.map((nodeId) => (
                <NodeLink key={nodeId} nodeId={nodeId} onOpen={onOpenNode} />
              ))}
            </div>
          )}
          {usedBy.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-fg-subtle">Used by</span>
              {usedBy.map((nodeId) => (
                <NodeLink key={nodeId} nodeId={nodeId} onOpen={onOpenNode} />
              ))}
            </div>
          )}
          {dependsOn.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-fg-subtle">Depends on</span>
              <span className="font-mono text-fg-muted">{dependsOn.join(", ")}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
