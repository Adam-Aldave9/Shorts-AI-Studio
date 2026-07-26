// Result screen: the final cut + a per-node cost breakdown. final_url lives in
// live run state (not the package spec), so we read it from the SSE stream — a completed
// run emits one frame carrying it; per-node costs come from the package GET.

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
import { getPackage } from "@/api/client";
import { useStatusStream } from "@/hooks/useStatusStream";
import { actualTotalUsd, videoShots } from "@/lib/package";
import { formatDuration, formatUsd } from "@/lib/format";
import { EmptyState, Spinner, Stat } from "@/components/ui";

export default function Result() {
  const { projectId = "" } = useParams();
  // Close the stream once the run completes so a finished run doesn't reconnect-loop.
  const event = useStatusStream(projectId, true);

  const packageQuery = useQuery({
    queryKey: ["package", projectId],
    queryFn: () => getPackage(projectId),
    enabled: Boolean(projectId),
  });

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
          <p className="font-mono text-xs text-fg-subtle">{projectId}</p>
        </div>
        <Link className="text-sm text-accent-soft underline hover:text-accent" to="/history">
          Back to history
        </Link>
      </div>

      {finalUrl ? (
        <div className="space-y-2">
          <video className="w-full rounded-xl border bg-black" src={finalUrl} controls />
          <a
            className="text-sm text-accent-soft underline hover:text-accent"
            href={finalUrl}
            download
          >
            Download MP4
          </a>
        </div>
      ) : (
        <EmptyState title="Render not finished yet">
          The final cut is not available.{" "}
          <Link className="underline" to={`/status/${projectId}`}>
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
        <div className="rounded-xl border bg-surface-raised p-4">
          <div className="mb-3 text-xs uppercase tracking-wide text-fg-subtle">
            Cost by node (estimated vs actual)
          </div>
          <ResponsiveContainer width="100%" height={Math.max(260, chartData.length * 26)}>
            <BarChart data={chartData} layout="vertical" margin={{ left: 16, right: 24 }}>
              <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#27272a" />
              <XAxis
                type="number"
                tickFormatter={(value) => `$${Number(value).toFixed(2)}`}
                tick={{ fill: "#a1a1aa", fontSize: 11 }}
                axisLine={{ stroke: "#3f3f46" }}
                tickLine={false}
              />
              <YAxis
                type="category"
                dataKey="node"
                width={130}
                tick={{ fill: "#a1a1aa", fontSize: 10 }}
                axisLine={false}
                tickLine={false}
              />
              <Tooltip
                formatter={(value) => formatUsd(Number(value))}
                cursor={{ fill: "rgba(255,255,255,0.04)" }}
                contentStyle={{
                  backgroundColor: "#18181b",
                  border: "1px solid #27272a",
                  borderRadius: 8,
                  color: "#f4f4f5",
                }}
                labelStyle={{ color: "#a1a1aa" }}
              />
              <Legend
                formatter={(value) => (
                  <span style={{ color: "#a1a1aa", fontSize: 12 }}>{value}</span>
                )}
              />
              <Bar dataKey="estimated" name="Estimated" fill="#3987e5" radius={[0, 4, 4, 0]} />
              <Bar dataKey="actual" name="Actual" fill="#8b5cf6" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
