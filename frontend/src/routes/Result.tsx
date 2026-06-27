// Result screen (spec §9.2): the final cut + a per-node cost breakdown. final_url
// lives in live run state (not the package spec), so we read it from the SSE stream
// (a completed run emits one frame carrying it); the package GET supplies per-node
// costs overlaid from the live node hashes.

import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { getPackage, openEvents, type StatusEvent } from "@/api/client";
import { actualTotalUsd, videoShots } from "@/lib/package";
import { formatDuration, formatUsd } from "@/lib/format";
import { EmptyState, Spinner, Stat } from "@/components/ui";

export default function Result() {
  const { projectId = "" } = useParams();
  const [event, setEvent] = useState<StatusEvent | null>(null);

  const packageQuery = useQuery({
    queryKey: ["package", projectId],
    queryFn: () => getPackage(projectId),
    enabled: Boolean(projectId),
  });

  useEffect(() => {
    if (!projectId) return;
    // A finished run emits one frame carrying final_url, then the server closes the
    // stream; close our side too so EventSource doesn't reconnect-loop on it.
    const source = openEvents(projectId, {
      onStatus: (incoming) => {
        setEvent(incoming);
        if (incoming.complete) source.close();
      },
    });
    return () => source.close();
  }, [projectId]);

  if (packageQuery.isLoading) return <Spinner label="Loading result..." />;
  const pkg = packageQuery.data;
  const finalUrl = event?.final_url ?? null;
  const totalCost = event?.cost_usd ?? (pkg ? actualTotalUsd(pkg) : 0);

  const chartData = (pkg?.assets ?? []).map((asset) => ({
    node: asset.node_id,
    estimated: asset.estimated_cost_usd ?? 0,
    actual: asset.actual_cost_usd ?? 0,
  }));

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">{pkg?.meta.title ?? "Result"}</h1>
          <p className="font-mono text-xs text-neutral-400">{projectId}</p>
        </div>
        <Link className="text-sm text-neutral-600 underline hover:text-neutral-900" to="/history">
          Back to history
        </Link>
      </div>

      {finalUrl ? (
        <div className="space-y-2">
          <video className="w-full rounded-lg border bg-black" src={finalUrl} controls />
          <a
            className="text-sm text-neutral-600 underline hover:text-neutral-900"
            href={finalUrl}
            download
          >
            Download MP4
          </a>
        </div>
      ) : (
        <EmptyState title="Render not finished yet">
          The final cut is not available. <Link className="underline" to={`/status/${projectId}`}>
            Watch execution
          </Link>{" "}
          and this page will fill in when it completes.
        </EmptyState>
      )}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Stat label="Total cost" value={formatUsd(totalCost)} />
        <Stat
          label="Critical path"
          value={event ? formatDuration(event.critical_path_s) : "-"}
          hint="theoretical floor"
        />
        <Stat label="Shots" value={pkg ? videoShots(pkg).length : 0} />
      </div>

      {chartData.length > 0 && (
        <div className="rounded-lg border bg-white p-4">
          <div className="mb-3 text-xs uppercase tracking-wide text-neutral-500">
            Cost by node (estimated vs actual)
          </div>
          <ResponsiveContainer width="100%" height={Math.max(260, chartData.length * 26)}>
            <BarChart data={chartData} layout="vertical" margin={{ left: 16, right: 24 }}>
              <CartesianGrid strokeDasharray="3 3" horizontal={false} />
              <XAxis type="number" tickFormatter={(value) => `$${Number(value).toFixed(2)}`} fontSize={11} />
              <YAxis type="category" dataKey="node" width={130} fontSize={10} />
              <Tooltip formatter={(value) => formatUsd(Number(value))} />
              <Legend />
              <Bar dataKey="estimated" name="Estimated" fill="#a3a3a3" />
              <Bar dataKey="actual" name="Actual" fill="#16a34a" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
