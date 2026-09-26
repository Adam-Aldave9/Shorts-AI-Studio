// The Review tab: everything the revision will change and regenerate, before it runs.

import type { RevisionPreview } from "@/api/client";
import { formatUsd } from "@/lib/format";
import {
  Button,
  Card,
  ErrorBanner,
  Field,
  Spinner,
  Stat,
  WarningBanner,
  controlClass,
} from "@/components/ui";

const REWRITTEN = new Set(["edited", "prompt", "new"]);

export function ReviewStep({
  preview,
  inPlace,
  note,
  onNote,
  canCreate,
  creating,
  onCreate,
}: {
  preview: RevisionPreview | null;
  inPlace: boolean;
  note: string;
  onNote: (note: string) => void;
  canCreate: boolean;
  creating: boolean;
  onCreate: () => void;
}) {
  if (!preview) return <Spinner label="Working out what this revision changes..." />;

  const replanned = Object.values(preview.shot_targets).reduce((sum, n) => sum + n, 0);
  const rewritten =
    Object.values(preview.shot_status).filter((status) => REWRITTEN.has(status)).length + replanned;

  return (
    <div className="space-y-4">
      <Card className="space-y-3">
        <h2 className="text-sm font-semibold">
          {inPlace
            ? "Update this draft in place"
            : `Create v${preview.next_version ?? "?"} of this film`}
        </h2>
        <p className="text-sm text-fg-muted">
          {inPlace
            ? "Nothing has rendered yet, so the draft itself is re-planned; no new version is made."
            : "The current version stays as it is. The new version reuses every render whose inputs didn't change."}
        </p>
        {preview.changes.length > 0 ? (
          <ul className="list-disc space-y-0.5 pl-5 text-sm text-fg-muted">
            {preview.changes.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-fg-subtle">
            {inPlace
              ? "No changes yet."
              : "No story changes: the new version re-cuts the same film, and you can choose shots to re-render at its checkpoint."}
          </p>
        )}
      </Card>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Scenes re-planned" value={preview.stale_scenes.length} />
        <Stat label="Prompts rewritten" value={rewritten} />
        <Stat label="Refs re-rendered" value={preview.rerendered_refs.length} />
        <Stat label="Narration" value={preview.narration_rerender ? "re-recorded" : "kept"} />
      </div>
      {!inPlace && preview.predicted_render !== null && (
        <div className="grid grid-cols-3 gap-3">
          <Stat label="Renders" value={`~${preview.predicted_render}`} hint="approximate" />
          <Stat label="Reused" value={`~${preview.predicted_reuse ?? 0}`} hint="for $0" />
          <Stat label="Render cost" value={`~${formatUsd(preview.predicted_cost_usd ?? 0)}`} />
        </div>
      )}

      {preview.errors.length > 0 && (
        <ErrorBanner title="Fix these before creating the revision" error={preview.errors} />
      )}
      {preview.warnings.map((warning) => (
        <WarningBanner key={warning}>{warning}</WarningBanner>
      ))}

      <Card className="space-y-3">
        <Field label="Describe this revision" hint="optional">
          <textarea
            className={controlClass}
            rows={2}
            value={note}
            placeholder="brighter ending, new narrator..."
            onChange={(event) => onNote(event.target.value)}
          />
        </Field>
        <Button disabled={!canCreate || creating} onClick={onCreate}>
          {creating ? "Starting..." : inPlace ? "Update draft" : "Create revision"}
        </Button>
      </Card>
    </div>
  );
}
