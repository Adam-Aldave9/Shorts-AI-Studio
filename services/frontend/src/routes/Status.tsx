// Status screen: live DAG view driven by the scheduler's SSE stream.

import { useEffect } from "react";
import { Link, useParams } from "react-router-dom";
import type { StatusEvent } from "@/api/client";
import { useStatusStream } from "@/hooks/useStatusStream";
import { useNavigateOnce } from "@/hooks/useNavigateOnce";
import { formatDuration, formatUsd } from "@/lib/format";
import { PhaseBadge, Spinner, StatusBadge, Stat, SuccessBanner } from "@/components/ui";

function countByStatus(event: StatusEvent, status: string): number {
  return Object.values(event.nodes).filter((node) => node.status === status).length;
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
  const pct = nodes.length ? `${Math.round((done / nodes.length) * 100)}%` : "0%";

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
        <Stat
          label="Failed"
          value={countByStatus(event, "failed") + countByStatus(event, "dead-lettered")}
        />
      </div>

      <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-surface-overlay">
        <div
          className="h-full rounded-full bg-accent transition-all duration-500"
          style={{ width: pct }}
        />
      </div>

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
            {node.error && <div className="mt-1 text-xs text-danger">{node.error}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}
