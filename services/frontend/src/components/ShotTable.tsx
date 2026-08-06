import type { ReactNode } from "react";
import type { Asset } from "@/api/client";
import { shotDurationS } from "@/lib/package";
import { formatDuration, formatUsd } from "@/lib/format";
import { Panel } from "@/components/Panel";

/** The per-shot Node/Prompt/Dur/Est table shared by the read-only checkpoint summary and
 *  the editable form. The prompt cell is caller-rendered so each host supplies its own
 *  read-only text or editable control. */
export function ShotTable({
  title,
  shots,
  maxHeightClass,
  renderPrompt,
}: {
  title: string;
  shots: Asset[];
  maxHeightClass: string;
  renderPrompt: (shot: Asset) => ReactNode;
}) {
  return (
    <Panel title={title}>
      <div className={`${maxHeightClass} overflow-auto`}>
        <table className="w-full text-left text-sm">
          <thead className="sticky top-0 bg-surface-overlay text-xs uppercase tracking-wide text-fg-subtle">
            <tr>
              <th className="px-4 py-2 font-medium">Node</th>
              <th className="px-4 py-2 font-medium">Prompt</th>
              <th className="px-4 py-2 text-right font-medium">Dur</th>
              <th className="px-4 py-2 text-right font-medium">Est.</th>
            </tr>
          </thead>
          <tbody>
            {shots.map((shot) => (
              <tr key={shot.node_id} className="border-t align-top">
                <td className="px-4 py-2 font-mono text-xs text-fg-subtle">{shot.node_id}</td>
                <td className="px-4 py-2">{renderPrompt(shot)}</td>
                <td className="px-4 py-2 text-right tabular-nums">
                  {formatDuration(shotDurationS(shot))}
                </td>
                <td className="px-4 py-2 text-right tabular-nums">
                  {formatUsd(shot.estimated_cost_usd ?? 0)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
