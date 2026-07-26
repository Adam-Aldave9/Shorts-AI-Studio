// Structured editing of a package's safe fields — the Checkpoint's default
// view, with Monaco behind an "Advanced (JSON)" toggle. Only meta + per-shot video
// prompts + voiceover text are editable; DAG structure stays raw-JSON-only so a merge can
// never corrupt the graph.

import { useEffect, useRef, useState } from "react";
import type { ProductionPackage } from "@/api/client";
import { estimatedTotalUsd, videoShots, voiceovers } from "@/lib/package";
import { formatUsd } from "@/lib/format";
import { Card, Field, controlClass } from "@/components/ui";
import { ShotTable } from "@/components/ShotTable";

/** A draft of only the editable fields. `budget_usd` is a string for input-friendly
 *  editing; it is coerced back to a number on merge. */
interface EditDraft {
  meta: {
    title: string;
    premise: string;
    style: string;
    aspect_ratio: string;
    narration_voice_id: string;
    budget_usd: string;
  };
  shots: Record<string, string>; // node_id -> video prompt
  voiceovers: Record<string, string>; // node_id -> voiceover text
}

function draftFromPackage(pkg: ProductionPackage): EditDraft {
  const shots: Record<string, string> = {};
  for (const shot of videoShots(pkg)) shots[shot.node_id] = shot.prompt ?? "";
  const voiceoverTexts: Record<string, string> = {};
  for (const voiceover of voiceovers(pkg)) voiceoverTexts[voiceover.node_id] = voiceover.text ?? "";
  return {
    meta: {
      title: pkg.meta.title,
      premise: pkg.meta.premise,
      style: pkg.meta.style,
      aspect_ratio: pkg.meta.aspect_ratio ?? "16:9",
      narration_voice_id: pkg.meta.narration_voice_id,
      budget_usd: String(pkg.meta.budget_usd),
    },
    shots,
    voiceovers: voiceoverTexts,
  };
}

/** Fold the draft back into the package immutably, preserving everything not edited (DAG,
 *  spec, statuses, durations, costs, world, timeline). */
function mergeDraft(pkg: ProductionPackage, draft: EditDraft): ProductionPackage {
  return {
    ...pkg,
    meta: { ...pkg.meta, ...draft.meta, budget_usd: Number(draft.meta.budget_usd) },
    assets: (pkg.assets ?? []).map((asset) =>
      asset.type === "video" && asset.node_id in draft.shots
        ? { ...asset, prompt: draft.shots[asset.node_id] }
        : asset.type === "voiceover" && asset.node_id in draft.voiceovers
          ? { ...asset, text: draft.voiceovers[asset.node_id] }
          : asset,
    ),
  };
}

interface Props {
  pkg: ProductionPackage;
  disabled: boolean;
  saving: boolean;
  /** Fired on every draft change with the merged package and whether it differs from the
   *  cached package — the Checkpoint host uses this for the Form->Advanced sync and the
   *  approve-with-unsaved-edits flow. */
  onDraftChange?: (merged: ProductionPackage, dirty: boolean) => void;
}

export default function PackageEditForm({ pkg, disabled, saving, onDraftChange }: Props) {
  const [draft, setDraft] = useState<EditDraft>(() => draftFromPackage(pkg));

  // Re-seed when the cached package identity changes (after a successful save rewrites the
  // query cache), mirroring Checkpoint's `initializedFor` pattern.
  const seededFor = useRef<ProductionPackage | null>(pkg);
  useEffect(() => {
    if (seededFor.current !== pkg) {
      seededFor.current = pkg;
      setDraft(draftFromPackage(pkg));
    }
  }, [pkg]);

  // Report the merged package + dirtiness upward. A flat compare against a fresh seed from
  // the cached package (the source of truth) detects pending edits.
  useEffect(() => {
    const dirty = JSON.stringify(draft) !== JSON.stringify(draftFromPackage(pkg));
    onDraftChange?.(mergeDraft(pkg, draft), dirty);
  }, [draft, pkg, onDraftChange]);

  const locked = disabled || saving;
  const voiceoverAssets = voiceovers(pkg);
  const budgetNum = Number(draft.meta.budget_usd);
  const estTotal = estimatedTotalUsd(pkg);
  const budgetLow = Number.isFinite(budgetNum) && budgetNum < estTotal;

  const setMeta = (key: keyof EditDraft["meta"], value: string) =>
    setDraft((current) => ({ ...current, meta: { ...current.meta, [key]: value } }));

  return (
    <div className="space-y-4">
      <Card className="space-y-4">
        <Field label="Title">
          <input
            className={controlClass}
            value={draft.meta.title}
            disabled={locked}
            onChange={(event) => setMeta("title", event.target.value)}
          />
        </Field>
        <Field label="Premise">
          <textarea
            className={controlClass}
            rows={4}
            value={draft.meta.premise}
            disabled={locked}
            onChange={(event) => setMeta("premise", event.target.value)}
          />
        </Field>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Style">
            <input
              className={controlClass}
              value={draft.meta.style}
              disabled={locked}
              onChange={(event) => setMeta("style", event.target.value)}
            />
          </Field>
          <Field label="Aspect ratio">
            <input
              className={controlClass}
              value={draft.meta.aspect_ratio}
              disabled={locked}
              onChange={(event) => setMeta("aspect_ratio", event.target.value)}
            />
          </Field>
          <Field label="Narration voice id">
            <input
              className={controlClass}
              value={draft.meta.narration_voice_id}
              disabled={locked}
              onChange={(event) => setMeta("narration_voice_id", event.target.value)}
            />
          </Field>
          <Field label="Budget (USD)" hint={`est. ${formatUsd(estTotal)}`}>
            <input
              className={controlClass}
              type="number"
              min={0}
              step={0.01}
              value={draft.meta.budget_usd}
              disabled={locked}
              onChange={(event) => setMeta("budget_usd", event.target.value)}
            />
          </Field>
        </div>
        {budgetLow && (
          <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
            Budget below estimated cost {formatUsd(estTotal)} — save will fail validation.
          </div>
        )}
      </Card>

      {voiceoverAssets.length > 0 && (
        <Card className="space-y-4">
          <div className="text-xs uppercase tracking-wide text-fg-subtle">Voiceover</div>
          {voiceoverAssets.map((voiceover) => (
            <Field key={voiceover.node_id} label={voiceover.node_id}>
              <textarea
                className={controlClass}
                rows={3}
                value={draft.voiceovers[voiceover.node_id] ?? ""}
                disabled={locked}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    voiceovers: { ...current.voiceovers, [voiceover.node_id]: event.target.value },
                  }))
                }
              />
            </Field>
          ))}
        </Card>
      )}

      <ShotTable
        title="Shot prompts"
        shots={videoShots(pkg)}
        maxHeightClass="max-h-96"
        renderPrompt={(shot) => (
          <textarea
            className={controlClass}
            rows={2}
            value={draft.shots[shot.node_id] ?? ""}
            disabled={locked}
            onChange={(event) =>
              setDraft((current) => ({
                ...current,
                shots: { ...current.shots, [shot.node_id]: event.target.value },
              }))
            }
          />
        )}
      />
    </div>
  );
}
