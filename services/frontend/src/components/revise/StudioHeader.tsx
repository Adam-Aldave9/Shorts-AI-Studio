import type { RevisionPreview } from "@/api/client";
import { formatUsd } from "@/lib/format";
import { Button } from "@/components/ui";
import { VersionBadge } from "@/components/versions/VersionBadge";

export function StudioHeader({
  title,
  projectId,
  inPlace,
  preview,
  previewing,
  canCreate,
  creating,
  onDiscard,
  onCreate,
}: {
  title: string;
  projectId: string;
  inPlace: boolean;
  preview: RevisionPreview | null;
  previewing: boolean;
  canCreate: boolean;
  creating: boolean;
  onDiscard: () => void;
  onCreate: () => void;
}) {
  const changes = preview?.changes.length ?? 0;
  return (
    <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3 pt-3">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <h1 className="truncate text-xl font-semibold">
            {inPlace ? "Edit story" : `Revise ${title}`}
          </h1>
          {!inPlace && preview?.next_version && <VersionBadge version={preview.next_version} />}
        </div>
        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-fg-subtle">
          <span>
            {inPlace ? "updates this draft" : `v${preview?.next_version ?? "?"} of this film`}
          </span>
          <span aria-hidden>·</span>
          <span className="font-mono">{projectId}</span>
          <span aria-hidden>·</span>
          <span>
            {changes} {changes === 1 ? "change" : "changes"}
          </span>
          {!inPlace && preview?.predicted_render != null && (
            <>
              <span aria-hidden>·</span>
              <span className="tabular-nums">
                ~{preview.predicted_render} renders, ~{formatUsd(preview.predicted_cost_usd ?? 0)}
              </span>
            </>
          )}
          {previewing && <span className="text-fg-subtle">(updating...)</span>}
        </div>
      </div>
      <div className="flex items-center gap-2">
        <Button variant="ghost" onClick={onDiscard} disabled={creating}>
          Discard
        </Button>
        <Button onClick={onCreate} disabled={!canCreate || creating}>
          {creating ? "Starting..." : inPlace ? "Update draft" : "Create revision"}
        </Button>
      </div>
    </div>
  );
}
