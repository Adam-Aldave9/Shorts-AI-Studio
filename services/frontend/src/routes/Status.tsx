// Status screen (spec §9.2): live DAG view driven by the scheduler's SSE stream.
// Node pills, cost-to-date, critical-path floor, in-flight / queue depth. When the
// run reaches `complete` the compositor has set final_url, so route to the Result.

import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { openEvents, type StatusEvent } from "@/api/client";
import { formatDuration, formatUsd } from "@/lib/format";
import { PhaseBadge, Spinner, StatusBadge, Stat, SuccessBanner } from "@/components/ui";

function countByStatus(event: StatusEvent, status: string): number {
  return Object.values(event.nodes).filter((node) => node.status === status).length;
}

export default function Status() {
  const { projectId = "" } = useParams();
  const navigate = useNavigate();
  const [event, setEvent] = useState<StatusEvent | null>(null);
  const navigated = useRef(false);

  useEffect(() => {
    if (!projectId) return;
    const source = openEvents(projectId, { onStatus: setEvent });
    return () => source.close();
  }, [projectId]);

  // Once the compositor has finished, hand off to the Result view (briefly showing
  // the completed state first).
  useEffect(() => {
    if (event?.complete && !navigated.current) {
      navigated.current = true;
      const timer = setTimeout(() => navigate(`/result/${projectId}`), 1200);
      return () => clearTimeout(timer);
    }
  }, [event, navigate, projectId]);

  if (!event) return <Spinner label="Connecting to run..." />;

  const nodes = Object.entries(event.nodes);
  const done = countByStatus(event, "succeeded");
  const pct = nodes.length ? `${Math.round((done / nodes.length) * 100)}%` : "0%";

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-semibold">Execution</h1>
          <PhaseBadge phase={event.phase} />
        </div>
        <p className="font-mono text-xs text-fg-subtle">{event.project_id}</p>
      </div>

      <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Cost to date" value={formatUsd(event.cost_usd)} />
        <Stat
          label="Critical path"
          value={formatDuration(event.critical_path_s)}
          hint="floor"
        />
        <Stat label="In flight" value={countByStatus(event, "dispatched")} />
        <Stat label="Queued" value={countByStatus(event, "pending")} />
        <Stat label="Done" value={countByStatus(event, "succeeded")} />
        <Stat label="Failed" value={countByStatus(event, "failed") + countByStatus(event, "dead-lettered")} />
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
