// Recovery surface for a run with failed nodes: what went wrong in plain language, and the
// actions that fix it in place. Everything that already rendered is kept.

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getPackage,
  retryNodes,
  type Asset,
  type ErrorCode,
  type SseNode,
  type StatusEvent,
} from "@/api/client";
import { describeFailure, type FailureAction } from "@/lib/nodeErrors";
import { Button, Card, ErrorBanner, StatusBadge } from "@/components/ui";
import { NodePromptEditor } from "./NodePromptEditor";

const FAILED = new Set(["failed", "dead-lettered"]);

function disabledReasonFor(phase: string | null): string | null {
  if (phase === "executing" || phase === "blocked") return null;
  if (phase === "paused") {
    return "This run is paused at its budget limit; raising the budget isn't supported yet.";
  }
  if (phase === "compositing" || phase === "complete") {
    return "This run has finished rendering; its shots can no longer be changed.";
  }
  return "This run is still starting; try again in a moment.";
}

function useRetry(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (nodeIds: string[]) => retryNodes(projectId, nodeIds),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["runPackage", projectId] }),
  });
}

function TechnicalDetails({ node }: { node: SseNode }) {
  if (!node.error_detail) return null;
  return (
    <details className="mt-2 text-xs text-fg-subtle">
      <summary className="cursor-pointer select-none hover:text-fg-muted">
        Technical details
      </summary>
      <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-all rounded bg-surface p-2 font-mono text-[11px]">
        {node.error_detail}
      </pre>
    </details>
  );
}

const ACTION_LABELS: Record<FailureAction, string> = {
  suggest: "Suggest fix",
  edit: "Edit",
  retry: "Retry",
};

type Editing = { nodeId: string; retry: boolean; autoSuggest: boolean } | null;

function NodeFailureCard({
  projectId,
  nodeId,
  node,
  asset,
  dependents,
  assetById,
  disabledReason,
}: {
  projectId: string;
  nodeId: string;
  node: SseNode;
  asset: Asset | undefined;
  dependents: string[];
  assetById: Map<string, Asset>;
  disabledReason: string | null;
}) {
  const [editing, setEditing] = useState<Editing>(null);
  const retry = useRetry(projectId);
  const failure = describeFailure(node.error_code, asset?.type ?? "video");
  const editsText = failure.actions.some((action) => action !== "retry");

  function run(action: FailureAction) {
    if (action === "retry") retry.mutate([nodeId]);
    else setEditing({ nodeId, retry: true, autoSuggest: action === "suggest" });
  }

  const editingAsset = editing ? assetById.get(editing.nodeId) : undefined;

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <span className="font-mono text-sm text-fg">{nodeId}</span>
          <StatusBadge status={node.status} />
        </div>
        {node.attempts > 0 && (
          <span className="text-xs text-fg-subtle">attempts: {node.attempts}</span>
        )}
      </div>
      <div className="mt-2 font-medium text-fg">{failure.title}</div>
      {node.error && <p className="mt-1 text-sm text-danger">{node.error}</p>}
      <p className="mt-1 text-sm text-fg-muted">{failure.remedy}</p>

      {dependents.length > 0 && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-fg-subtle">
          <span>Also blocks:</span>
          {dependents.map((dependent) => (
            <span key={dependent} className="inline-flex items-center gap-1">
              <span className="font-mono text-fg-muted">{dependent}</span>
              {assetById.get(dependent)?.type !== "image" && (
                <button
                  type="button"
                  className="text-accent-soft underline hover:text-accent disabled:opacity-50"
                  disabled={Boolean(disabledReason)}
                  onClick={() =>
                    setEditing({ nodeId: dependent, retry: false, autoSuggest: false })
                  }
                >
                  Edit
                </button>
              )}
            </span>
          ))}
        </div>
      )}

      {!editing && (
        <div className="mt-3 flex flex-wrap gap-2">
          {failure.actions.map((action, index) => (
            <Button
              key={action}
              variant={index === 0 ? "primary" : "secondary"}
              className="px-3 py-1.5 text-xs"
              disabled={
                Boolean(disabledReason) || retry.isPending || (action !== "retry" && !asset)
              }
              onClick={() => run(action)}
            >
              {action === "retry" && editsText ? "Try again unchanged" : ACTION_LABELS[action]}
            </Button>
          ))}
        </div>
      )}
      {disabledReason && <p className="mt-2 text-xs text-fg-subtle">{disabledReason}</p>}
      {retry.isError && (
        <div className="mt-2">
          <ErrorBanner title="Could not retry" error={retry.error} />
        </div>
      )}

      {editing && editingAsset && (
        <NodePromptEditor
          key={editing.nodeId}
          projectId={projectId}
          asset={editingAsset}
          retry={editing.retry}
          autoSuggest={editing.autoSuggest}
          disabledReason={disabledReason}
          onClose={() => setEditing(null)}
        />
      )}
      <TechnicalDetails node={node} />
    </Card>
  );
}

function SystemicFailureCard({
  projectId,
  code,
  nodeIds,
  message,
  disabledReason,
}: {
  projectId: string;
  code: ErrorCode | null;
  nodeIds: string[];
  message: string | null;
  disabledReason: string | null;
}) {
  const retry = useRetry(projectId);
  const failure = describeFailure(code, "video");
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="font-medium text-fg">{failure.title}</div>
        <Button
          className="px-3 py-1.5 text-xs"
          disabled={Boolean(disabledReason) || retry.isPending}
          onClick={() => retry.mutate(nodeIds)}
        >
          {retry.isPending ? "Retrying..." : nodeIds.length > 1 ? "Retry all" : "Retry"}
        </Button>
      </div>
      {message && <p className="mt-1 text-sm text-danger">{message}</p>}
      <p className="mt-1 text-sm text-fg-muted">{failure.remedy}</p>
      <p className="mt-2 font-mono text-xs text-fg-subtle">{nodeIds.join(", ")}</p>
      {disabledReason && <p className="mt-2 text-xs text-fg-subtle">{disabledReason}</p>}
      {retry.isError && (
        <div className="mt-2">
          <ErrorBanner title="Could not retry" error={retry.error} />
        </div>
      )}
    </Card>
  );
}

export function FailurePanel({ projectId, event }: { projectId: string; event: StatusEvent }) {
  // Not the Checkpoint's ["package", id]: that entry holds local draft edits pinned with
  // staleTime Infinity, and this view needs the server's current prompts.
  const runPackage = useQuery({
    queryKey: ["runPackage", projectId],
    queryFn: () => getPackage(projectId),
    staleTime: 0,
  });

  const failed = Object.entries(event.nodes).filter(([, node]) => FAILED.has(node.status));
  if (failed.length === 0) return null;

  const assetById = new Map((runPackage.data?.assets ?? []).map((asset) => [asset.node_id, asset]));
  const disabledReason = disabledReasonFor(event.phase);

  const dependentsOf = new Map<string, string[]>();
  for (const [nodeId, node] of Object.entries(event.nodes)) {
    for (const upstream of node.blocked_by ?? []) {
      dependentsOf.set(upstream, [...(dependentsOf.get(upstream) ?? []), nodeId]);
    }
  }

  const systemic = new Map<ErrorCode | null, [string, SseNode][]>();
  const individual: [string, SseNode][] = [];
  for (const entry of failed) {
    const [nodeId, node] = entry;
    const type = assetById.get(nodeId)?.type ?? "video";
    if (describeFailure(node.error_code, type).systemic) {
      systemic.set(node.error_code, [...(systemic.get(node.error_code) ?? []), entry]);
    } else {
      individual.push(entry);
    }
  }

  return (
    <section className="mt-6 space-y-3" aria-label="Failed nodes">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-fg-subtle">
        Needs attention ({failed.length})
      </h2>
      {runPackage.isError && (
        <ErrorBanner title="Could not load the prompts" error={runPackage.error} />
      )}
      {[...systemic.entries()].map(([code, entries]) => (
        <SystemicFailureCard
          key={code ?? "none"}
          projectId={projectId}
          code={code}
          nodeIds={entries.map(([nodeId]) => nodeId)}
          message={entries[0][1].error}
          disabledReason={disabledReason}
        />
      ))}
      {individual.map(([nodeId, node]) => (
        <NodeFailureCard
          key={nodeId}
          projectId={projectId}
          nodeId={nodeId}
          node={node}
          asset={assetById.get(nodeId)}
          dependents={dependentsOf.get(nodeId) ?? []}
          assetById={assetById}
          disabledReason={disabledReason}
        />
      ))}
    </section>
  );
}
