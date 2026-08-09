// Run-critical numbers plus the action cluster, shown on every checkpoint tab. The host owns
// the sticky wrapper, since the tab strip pins with it as one block.

import type { ProductionPackage } from "@/api/client";
import { estimatedTotalUsd, videoShots } from "@/lib/package";
import { formatDuration, formatUsd } from "@/lib/format";
import { Button, ProgressBar, cn } from "@/components/ui";

function budgetFraction(estimate: number, budget: number): number {
  if (!Number.isFinite(budget) || budget <= 0) return estimate > 0 ? 1 : 0;
  return estimate / budget;
}

export function CheckpointHeader({
  pkg,
  locked,
  approved,
  dirty,
  saving,
  approving,
  onSave,
  onApprove,
  onRevert,
  onLeave,
}: {
  pkg: ProductionPackage;
  locked: boolean;
  approved: boolean;
  dirty: boolean;
  saving: boolean;
  approving: boolean;
  onSave: () => void;
  onApprove: () => void;
  onRevert: () => void;
  onLeave: () => void;
}) {
  const estimate = estimatedTotalUsd(pkg);
  const budget = pkg.meta.budget_usd;
  const fraction = budgetFraction(estimate, budget);
  const over = estimate > budget;
  const busy = saving || approving;

  return (
    <div className="pt-3">
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-xl font-semibold">{pkg.meta.title}</h1>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-fg-subtle">
            <span className="font-mono">{pkg.project_id}</span>
            <span aria-hidden>·</span>
            <span>{approved ? "Approved" : "Draft"}</span>
            {!approved && dirty && (
              <>
                <span aria-hidden>·</span>
                <span className="font-medium text-warning">Unsaved changes</span>
              </>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          {!locked && dirty && (
            <Button variant="ghost" onClick={onRevert} disabled={busy}>
              Revert all
            </Button>
          )}
          <Button variant="danger" onClick={onLeave} disabled={busy}>
            {approved ? "Back" : "Reject"}
          </Button>
          {!approved && (
            <>
              <Button variant="secondary" onClick={onSave} disabled={busy || locked}>
                {saving ? "Saving..." : "Save changes"}
              </Button>
              <Button onClick={onApprove} disabled={busy || locked}>
                {approving ? "Approving..." : "Approve & run"}
              </Button>
            </>
          )}
        </div>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-fg-subtle">
        <span className="tabular-nums">{formatDuration(pkg.meta.target_duration_s)}</span>
        <span aria-hidden>·</span>
        <span className="tabular-nums">{videoShots(pkg).length} shots</span>
        <span aria-hidden>·</span>
        <span className={cn("tabular-nums", over && "text-danger")}>
          {formatUsd(estimate)} of {formatUsd(budget)}
        </span>
        <ProgressBar
          className="w-32"
          fraction={fraction}
          tone={over ? "danger" : fraction > 0.9 ? "warning" : "accent"}
          label={`Estimated cost ${formatUsd(estimate)} of a ${formatUsd(budget)} budget`}
        />
        <span className="tabular-nums">{Math.round(fraction * 100)}%</span>
      </div>
    </div>
  );
}
