// The Cost tab: estimated vs actual spend per node.

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
import type { ProductionPackage } from "@/api/client";
import { formatUsd } from "@/lib/format";
import { EmptyState } from "@/components/ui";

// Recharts takes colors as props, not classes, so the design tokens have to be read out of
// the stylesheet rather than applied through Tailwind.
const token = (name: string): string => `rgb(var(--color-${name}))`;

export function CostPanel({ pkg }: { pkg: ProductionPackage }) {
  const data = (pkg.assets ?? []).map((asset) => ({
    node: asset.node_id,
    estimated: asset.estimated_cost_usd ?? 0,
    actual: asset.actual_cost_usd ?? 0,
  }));

  if (data.length === 0) {
    return <EmptyState title="No cost data">This package has no nodes.</EmptyState>;
  }

  return (
    <div className="rounded-xl border bg-surface-raised p-4">
      <div className="mb-3 text-xs uppercase tracking-wide text-fg-subtle">
        Cost by node (estimated vs actual)
      </div>
      <ResponsiveContainer width="100%" height={Math.max(260, data.length * 26)}>
        <BarChart data={data} layout="vertical" margin={{ left: 16, right: 24 }}>
          <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke={token("border")} />
          <XAxis
            type="number"
            tickFormatter={(value) => `$${Number(value).toFixed(2)}`}
            tick={{ fill: token("fg-muted"), fontSize: 11 }}
            axisLine={{ stroke: token("border-strong") }}
            tickLine={false}
          />
          <YAxis
            type="category"
            dataKey="node"
            width={130}
            tick={{ fill: token("fg-muted"), fontSize: 10 }}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip
            formatter={(value) => formatUsd(Number(value))}
            cursor={{ fill: "rgba(255,255,255,0.04)" }}
            contentStyle={{
              backgroundColor: token("surface-raised"),
              border: `1px solid ${token("border")}`,
              borderRadius: 8,
              color: token("fg"),
            }}
            labelStyle={{ color: token("fg-muted") }}
          />
          <Legend
            formatter={(value) => (
              <span style={{ color: token("fg-muted"), fontSize: 12 }}>{value}</span>
            )}
          />
          <Bar dataKey="estimated" name="Estimated" fill={token("chart-1")} radius={[0, 4, 4, 0]} />
          <Bar dataKey="actual" name="Actual" fill={token("chart-2")} radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
