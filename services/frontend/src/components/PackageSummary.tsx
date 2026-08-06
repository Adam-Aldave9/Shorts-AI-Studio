import type { ProductionPackage } from "@/api/client";
import { estimatedTotalUsd, videoShots, voiceovers } from "@/lib/package";
import { formatDuration, formatUsd } from "@/lib/format";
import { Card, Stat } from "@/components/ui";
import { ShotTable } from "@/components/ShotTable";

/** Read-only rendering of a production package (the Checkpoint's left pane): headline
 *  stats, meta, narration, and the shot list. */
export function PackageSummary({ pkg }: { pkg: ProductionPackage }) {
  const shots = videoShots(pkg);
  const narration = voiceovers(pkg)[0]?.text ?? null;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-3">
        <Stat label="Shots" value={shots.length} />
        <Stat label="Est. cost" value={formatUsd(estimatedTotalUsd(pkg))} />
        <Stat label="Budget" value={formatUsd(pkg.meta.budget_usd)} />
      </div>

      <Card>
        <dl className="grid grid-cols-3 gap-y-2 text-sm">
          <dt className="text-fg-subtle">Duration</dt>
          <dd className="col-span-2">{formatDuration(pkg.meta.target_duration_s)}</dd>
          <dt className="text-fg-subtle">Style</dt>
          <dd className="col-span-2">{pkg.meta.style}</dd>
          <dt className="text-fg-subtle">Aspect</dt>
          <dd className="col-span-2">{pkg.meta.aspect_ratio}</dd>
          <dt className="text-fg-subtle">Premise</dt>
          <dd className="col-span-2 text-fg-muted">{pkg.meta.premise}</dd>
        </dl>
      </Card>

      {narration && (
        <Card>
          <div className="text-xs uppercase tracking-wide text-fg-subtle">Narration</div>
          <p className="mt-2 whitespace-pre-wrap text-sm text-fg-muted">{narration}</p>
        </Card>
      )}

      <ShotTable
        title="Shot list"
        shots={shots}
        maxHeightClass="max-h-80"
        renderPrompt={(shot) => (
          <>
            <div className="line-clamp-2 text-fg-muted">{shot.prompt ?? "-"}</div>
            {shot.provider_hint && (
              <div className="font-mono text-[10px] text-fg-subtle">{shot.provider_hint}</div>
            )}
          </>
        )}
      />
    </div>
  );
}
