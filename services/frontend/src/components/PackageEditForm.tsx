// Structured, friendly editing for the safe fields of a production package
// (spec §4.3) — the default view on the Checkpoint screen, with Monaco kept behind
// an "Advanced (JSON)" toggle. Only meta fields + per-shot video prompts + voiceover
// text are editable here; DAG structure (node_id, depends_on, reference images, asset
// type, durations, costs) stays raw-JSON-only, so a merge can never corrupt the graph.

import { useEffect, useRef, useState } from "react";
import type { ProductionPackage } from "@/api/client";
import { estimatedTotalUsd, shotDurationS, videoShots, voiceovers } from "@/lib/package";
import { formatDuration, formatUsd } from "@/lib/format";
import { Card, Field, controlClass } from "@/components/ui";

/** A draft of *only* the editable fields. `budget_usd` is a string for input-friendly
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

export function draftFromPackage(pkg: ProductionPackage): EditDraft {
  const shots: Record<string, string> = {};
  for (const shot of videoShots(pkg)) shots[shot.node_id] = shot.prompt ?? "";
  const vos: Record<string, string> = {};
  for (const vo of voiceovers(pkg)) vos[vo.node_id] = vo.text ?? "";
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
    voiceovers: vos,
  };
}

/** Fold the draft back into the package immutably, preserving everything not edited
 *  (DAG, spec, statuses, durations, costs, world, timeline). */
export function mergeDraft(pkg: ProductionPackage, d: EditDraft): ProductionPackage {
  return {
    ...pkg,
    meta: { ...pkg.meta, ...d.meta, budget_usd: Number(d.meta.budget_usd) },
    assets: (pkg.assets ?? []).map((a) =>
      a.type === "video" && a.node_id in d.shots
        ? { ...a, prompt: d.shots[a.node_id] }
        : a.type === "voiceover" && a.node_id in d.voiceovers
          ? { ...a, text: d.voiceovers[a.node_id] }
          : a,
    ),
  };
}

interface Props {
  pkg: ProductionPackage;
  disabled: boolean;
  saving: boolean;
  /** Fired on every draft change with the merged package and whether it differs from
   *  the cached package — the Checkpoint host reads this for the Form->Advanced sync
   *  and the approve-with-unsaved-edits flow. */
  onDraftChange?: (merged: ProductionPackage, dirty: boolean) => void;
}

export default function PackageEditForm({ pkg, disabled, saving, onDraftChange }: Props) {
  const [draft, setDraft] = useState<EditDraft>(() => draftFromPackage(pkg));
  // Re-seed when the cached package identity changes (i.e. after a successful save
  // re-writes the query cache), mirroring Checkpoint's `initializedFor` pattern.
  const seededFor = useRef<ProductionPackage | null>(pkg);
  useEffect(() => {
    if (seededFor.current !== pkg) {
      seededFor.current = pkg;
      setDraft(draftFromPackage(pkg));
    }
  }, [pkg]);

  // Report the merged package + dirtiness upward. Flat compare against a fresh seed
  // from the cached package (source of truth) tells us if there are pending edits.
  useEffect(() => {
    const dirty = JSON.stringify(draft) !== JSON.stringify(draftFromPackage(pkg));
    onDraftChange?.(mergeDraft(pkg, draft), dirty);
  }, [draft, pkg, onDraftChange]);

  const locked = disabled || saving;
  const shots = videoShots(pkg);
  const vos = voiceovers(pkg);
  const budgetNum = Number(draft.meta.budget_usd);
  const estTotal = estimatedTotalUsd(pkg);
  const budgetLow = Number.isFinite(budgetNum) && budgetNum < estTotal;

  const setMeta = (key: keyof EditDraft["meta"], value: string) =>
    setDraft((d) => ({ ...d, meta: { ...d.meta, [key]: value } }));

  return (
    <div className="space-y-4">
      <Card className="space-y-4">
        <Field label="Title">
          <input
            className={controlClass}
            value={draft.meta.title}
            disabled={locked}
            onChange={(e) => setMeta("title", e.target.value)}
          />
        </Field>
        <Field label="Premise">
          <textarea
            className={controlClass}
            rows={4}
            value={draft.meta.premise}
            disabled={locked}
            onChange={(e) => setMeta("premise", e.target.value)}
          />
        </Field>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Style">
            <input
              className={controlClass}
              value={draft.meta.style}
              disabled={locked}
              onChange={(e) => setMeta("style", e.target.value)}
            />
          </Field>
          <Field label="Aspect ratio">
            <input
              className={controlClass}
              value={draft.meta.aspect_ratio}
              disabled={locked}
              onChange={(e) => setMeta("aspect_ratio", e.target.value)}
            />
          </Field>
          <Field label="Narration voice id">
            <input
              className={controlClass}
              value={draft.meta.narration_voice_id}
              disabled={locked}
              onChange={(e) => setMeta("narration_voice_id", e.target.value)}
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
              onChange={(e) => setMeta("budget_usd", e.target.value)}
            />
          </Field>
        </div>
        {budgetLow && (
          <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
            Budget below estimated cost {formatUsd(estTotal)} — save will fail validation.
          </div>
        )}
      </Card>

      {vos.length > 0 && (
        <Card className="space-y-4">
          <div className="text-xs uppercase tracking-wide text-fg-subtle">Voiceover</div>
          {vos.map((vo) => (
            <Field key={vo.node_id} label={vo.node_id}>
              <textarea
                className={controlClass}
                rows={3}
                value={draft.voiceovers[vo.node_id] ?? ""}
                disabled={locked}
                onChange={(e) =>
                  setDraft((d) => ({
                    ...d,
                    voiceovers: { ...d.voiceovers, [vo.node_id]: e.target.value },
                  }))
                }
              />
            </Field>
          ))}
        </Card>
      )}

      <div className="overflow-hidden rounded-xl border bg-surface-raised">
        <div className="bg-surface-overlay px-4 py-2 text-xs uppercase tracking-wide text-fg-subtle">
          Shot prompts
        </div>
        <div className="max-h-96 overflow-auto">
          <table className="w-full text-left text-sm">
            <thead className="sticky top-0 bg-surface-overlay text-xs uppercase tracking-wide text-fg-subtle">
              <tr>
                <th className="px-4 py-2 font-medium">Node</th>
                <th className="px-4 py-2 font-medium">Prompt</th>
                <th className="px-4 py-2 text-right font-medium">Dur</th>
                <th className="px-4 py-2 text-right font-medium">Est.</th>
              </tr>
            </thead>
            <tbody>
              {shots.map((shot) => (
                <tr key={shot.node_id} className="border-t align-top">
                  <td className="px-4 py-2 font-mono text-xs text-fg-subtle">{shot.node_id}</td>
                  <td className="px-4 py-2">
                    <textarea
                      className={controlClass}
                      rows={2}
                      value={draft.shots[shot.node_id] ?? ""}
                      disabled={locked}
                      onChange={(e) =>
                        setDraft((d) => ({
                          ...d,
                          shots: { ...d.shots, [shot.node_id]: e.target.value },
                        }))
                      }
                    />
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums">
                    {formatDuration(shotDurationS(shot))}
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums">
                    {formatUsd(shot.estimated_cost_usd ?? 0)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
