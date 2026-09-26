// Status screen: live DAG view driven by the scheduler's SSE stream.

import { useEffect } from "react";
import { Link, useParams } from "react-router-dom";
import type { SseNode, StatusEvent } from "@/api/client";
import { useStatusStream } from "@/hooks/useStatusStream";
import { useNavigateOnce } from "@/hooks/useNavigateOnce";
import { formatDuration, formatUsd } from "@/lib/format";
import { describeFailure } from "@/lib/nodeErrors";
import {
  PhaseBadge,
  ProgressBar,
  Spinner,
  StatusBadge,
  Stat,
  SuccessBanner,
  WarningBanner,
} from "@/components/ui";
import { FailurePanel } from "@/components/status/FailurePanel";

function countByStatus(event: StatusEvent, status: string): number {
  return Object.values(event.nodes).filter((node) => node.status === status).length;
}

function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

function NodeNote({ node }: { node: SseNode }) {
  if (node.status === "failed" || node.status === "dead-lettered") {
    // The grid has no asset types; the title is the same for every type.
    return (
      <div className="mt-1 text-xs text-danger">
        {describeFailure(node.error_code, "video").title}
      </div>
    );
  }
  if (node.status === "pending" && node.blocked_by?.length) {
    return (
      <div className="mt-1 text-xs text-fg-subtle">Waiting on {node.blocked_by.join(", ")}</div>
    );
  }
  return null;
}

export default function Status() {
  const { projectId = "" } = useParams();
  const event = useStatusStream(projectId);
  const navigateOnce = useNavigateOnce();

  // Delayed so the completed state is visible before handing off to Result.
  useEffect(() => {
    if (!event?.complete) return;
    const timer = setTimeout(() => navigateOnce(`/result/${projectId}`), 1200);
    return () => clearTimeout(timer);
  }, [event, navigateOnce, projectId]);

  if (!event) return <Spinner label="Connecting to run..." />;

  const nodes = Object.entries(event.nodes);
  const done = countByStatus(event, "succeeded");
  const failed = countByStatus(event, "failed") + countByStatus(event, "dead-lettered");

  return (
    <div className="mx-auto max-w-5xl">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-semibold">Execution</h1>
          <PhaseBadge phase={event.phase} />
        </div>
        <p className="font-mono text-xs text-fg-subtle">{event.project_id}</p>
      </div>

      <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Cost to date" value={formatUsd(event.cost_usd)} />
        <Stat label="Critical path" value={formatDuration(event.critical_path_s)} hint="floor" />
        <Stat label="In flight" value={countByStatus(event, "dispatched")} />
        <Stat label="Queued" value={countByStatus(event, "pending")} />
        <Stat label="Done" value={countByStatus(event, "succeeded")} />
        <Stat label="Failed" value={failed} />
      </div>

      <ProgressBar
        className="mt-4"
        fraction={nodes.length ? done / nodes.length : 0}
        label={`${done} of ${nodes.length} nodes rendered`}
      />

      {event.phase === "blocked" && (
        <WarningBanner className="mt-4">
          Needs your input - {plural(failed, "shot")} failed. Your {plural(done, "finished asset")}{" "}
          {done === 1 ? "is" : "are"} kept; only the shots you fix will re-render.
        </WarningBanner>
      )}
      {event.phase === "paused" && (
        <WarningBanner className="mt-4">
          Paused - the next shot would exceed this run&apos;s budget. Finished assets are kept.
        </WarningBanner>
      )}

      {event.complete && (
        <div className="mt-4">
          <SuccessBanner>
            Render complete - opening the result...{" "}
            <Link className="font-medium underline" to={`/result/${projectId}`}>
              view now
            </Link>
          </SuccessBanner>
        </div>
      )}

      <FailurePanel projectId={projectId} event={event} />

      <div className="mt-6 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {nodes.map(([nodeId, node]) => (
          <div key={nodeId} className="rounded-md border bg-surface-raised px-3 py-2">
            <div className="flex items-center justify-between gap-2">
              <span className="truncate font-mono text-xs text-fg-muted">{nodeId}</span>
              <StatusBadge status={node.status} />
            </div>
            {node.attempts > 1 && (
              <div className="mt-1 text-xs text-fg-subtle">attempts: {node.attempts}</div>
            )}
            <NodeNote node={node} />
          </div>
        ))}
      </div>
    </div>
  );
}
