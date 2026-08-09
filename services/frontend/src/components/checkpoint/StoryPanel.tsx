// The Story tab: the package's meta fields plus the narration.

import type { ProductionPackage } from "@/api/client";
import type { PackageDraftApi } from "@/hooks/usePackageDraft";
import { estimatedTotalUsd, voiceovers } from "@/lib/package";
import { formatUsd } from "@/lib/format";
import { Card, Field, WarningBanner, controlClass } from "@/components/ui";

export function StoryPanel({
  pkg,
  draft,
  setMeta,
  setNode,
  readOnly,
}: Pick<PackageDraftApi, "draft" | "setMeta" | "setNode"> & {
  pkg: ProductionPackage;
  readOnly: boolean;
}) {
  const narrations = voiceovers(pkg);
  const estimate = estimatedTotalUsd(pkg);
  const budget = Number(draft.meta.budget_usd);
  const budgetLow = Number.isFinite(budget) && budget < estimate;

  return (
    <div className="space-y-4">
      <Card className="space-y-4">
        <Field label="Title">
          <input
            className={controlClass}
            value={draft.meta.title}
            disabled={readOnly}
            onChange={(event) => setMeta("title", event.target.value)}
          />
        </Field>
        <Field label="Premise">
          <textarea
            className={controlClass}
            rows={4}
            value={draft.meta.premise}
            disabled={readOnly}
            onChange={(event) => setMeta("premise", event.target.value)}
          />
        </Field>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Style">
            <input
              className={controlClass}
              value={draft.meta.style}
              disabled={readOnly}
              onChange={(event) => setMeta("style", event.target.value)}
            />
          </Field>
          <Field label="Aspect ratio">
            <input
              className={controlClass}
              value={draft.meta.aspect_ratio}
              disabled={readOnly}
              onChange={(event) => setMeta("aspect_ratio", event.target.value)}
            />
          </Field>
          <Field label="Narration voice id">
            <input
              className={controlClass}
              value={draft.meta.narration_voice_id}
              disabled={readOnly}
              onChange={(event) => setMeta("narration_voice_id", event.target.value)}
            />
          </Field>
          <Field label="Budget (USD)" hint={`est. ${formatUsd(estimate)}`}>
            <input
              className={controlClass}
              type="number"
              min={0}
              step={0.01}
              value={draft.meta.budget_usd}
              disabled={readOnly}
              onChange={(event) => setMeta("budget_usd", event.target.value)}
            />
          </Field>
        </div>
        {budgetLow && (
          <WarningBanner className="px-3 py-2 text-xs">
            Budget below estimated cost {formatUsd(estimate)} — save will fail validation.
          </WarningBanner>
        )}
      </Card>

      {narrations.length > 0 && (
        <Card className="space-y-4">
          <div className="text-xs uppercase tracking-wide text-fg-subtle">Narration</div>
          {narrations.map((voiceover) => (
            <Field key={voiceover.node_id} label={voiceover.node_id}>
              <textarea
                className={controlClass}
                rows={6}
                value={draft.nodes[voiceover.node_id] ?? ""}
                disabled={readOnly}
                onChange={(event) => setNode(voiceover.node_id, event.target.value)}
              />
            </Field>
          ))}
        </Card>
      )}
    </div>
  );
}
