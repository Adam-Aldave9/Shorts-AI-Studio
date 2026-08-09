// History screen: every persisted run, newest first, each row linking to the screen for its
// phase.

import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { listPackages, type PackageSummary } from "@/api/client";
import { formatUsd, relativeTime, formatDateTime } from "@/lib/format";
import { Button, EmptyState, ErrorBanner, PhaseBadge, Spinner } from "@/components/ui";
import { Panel } from "@/components/Panel";

function destination(summary: PackageSummary): string {
  if (summary.phase === "complete") return `/result/${summary.project_id}`;
  if (summary.phase === "executing" || summary.phase === "compositing") {
    return `/status/${summary.project_id}`;
  }
  return `/checkpoint/${summary.project_id}`;
}

export default function History() {
  const navigate = useNavigate();
  const query = useQuery({
    queryKey: ["packages"],
    queryFn: listPackages,
    refetchInterval: 5000,
  });

  return (
    <div className="mx-auto max-w-5xl">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">History</h1>
        <Button variant="secondary" onClick={() => query.refetch()} disabled={query.isFetching}>
          {query.isFetching ? "Refreshing..." : "Refresh"}
        </Button>
      </div>

      <div className="mt-6">
        {query.isLoading && <Spinner label="Loading runs..." />}
        {query.isError && <ErrorBanner title="Could not load runs" error={query.error} />}
        {query.data && query.data.length === 0 && (
          <EmptyState title="No runs yet">Submit a brief to get started.</EmptyState>
        )}

        {query.data && query.data.length > 0 && (
          <Panel>
            <table className="w-full text-left text-sm">
              <thead className="bg-surface-overlay text-xs uppercase tracking-wide text-fg-subtle">
                <tr>
                  <th className="px-4 py-2 font-medium">Title</th>
                  <th className="px-4 py-2 font-medium">Created</th>
                  <th className="px-4 py-2 font-medium">Phase</th>
                  <th className="px-4 py-2 text-right font-medium">Cost</th>
                </tr>
              </thead>
              <tbody>
                {query.data.map((summary) => (
                  <tr
                    key={summary.project_id}
                    className="cursor-pointer border-t transition-colors hover:bg-surface-overlay/50"
                    onClick={() => navigate(destination(summary))}
                  >
                    <td className="px-4 py-3">
                      <div className="font-medium text-fg">{summary.title}</div>
                      <div className="font-mono text-xs text-fg-subtle">{summary.project_id}</div>
                    </td>
                    <td
                      className="px-4 py-3 text-fg-muted"
                      title={formatDateTime(summary.created_at)}
                    >
                      {relativeTime(summary.created_at)}
                    </td>
                    <td className="px-4 py-3">
                      <PhaseBadge phase={summary.phase} />
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {formatUsd(summary.cost_usd)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        )}
      </div>
    </div>
  );
}
