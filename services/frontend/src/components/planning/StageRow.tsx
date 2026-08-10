import type { PlanningStageDetail } from "@/api/client";
import { formatDuration } from "@/lib/format";
import { cn, IndeterminateBar, ProgressBar } from "@/components/ui";
import { detailFraction, renderDetail, type StageSpec } from "./stages";

export type StageState = "done" | "active" | "pending";

// Past this multiple of the stage's typical duration the readout says so, rather than
// leaving the user to wonder whether the job is hung.
const SLOW_FACTOR = 2;

function Marker({ state }: { state: StageState }) {
  if (state === "done") {
    return (
      <svg className="h-4 w-4 text-success" viewBox="0 0 16 16" fill="none" aria-hidden>
        <path d="M3 8.5l3 3 7-7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      </svg>
    );
  }
  if (state === "active") {
    return (
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-surface-overlay border-t-accent" />
    );
  }
  return <span className="h-3 w-3 rounded-full border-2 border-border" />;
}

export function StageRow({
  spec,
  state,
  detail,
  elapsedS,
}: {
  spec: StageSpec;
  state: StageState;
  detail: PlanningStageDetail | undefined;
  /** Seconds this stage ran (final when done, live when active). */
  elapsedS: number | null;
}) {
  const line = renderDetail(spec.key, detail);
  const fraction = detailFraction(detail);
  const slow = state === "active" && elapsedS !== null && elapsedS > SLOW_FACTOR * spec.typicalS;

  return (
    <li
      className="flex gap-3"
      aria-current={state === "active" ? "step" : undefined}
      data-stage={spec.key}
    >
      <span className="flex h-5 w-4 shrink-0 items-center justify-center">
        <Marker state={state} />
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-3">
          <span
            className={cn(
              "text-sm",
              state === "pending" ? "text-fg-subtle" : "text-fg",
              state === "active" && "font-medium",
            )}
          >
            {spec.label}
          </span>
          <span
            className={cn(
              "shrink-0 text-xs tabular-nums",
              slow ? "text-warning" : "text-fg-subtle",
            )}
          >
            {state === "pending"
              ? `~${spec.typicalS}s`
              : elapsedS === null
                ? ""
                : formatDuration(elapsedS)}
            {slow && " - taking longer than usual"}
          </span>
        </div>

        {state === "active" && <p className="mt-0.5 text-xs text-fg-muted">{spec.explainer}</p>}
        {line && (
          <p className={cn("mt-0.5 text-xs", state === "done" ? "text-fg-muted" : "text-fg")}>
            {line}
          </p>
        )}
        {state === "active" &&
          (fraction === null ? (
            <IndeterminateBar className="mt-2" label={`${spec.label} in progress`} />
          ) : (
            <ProgressBar
              className="mt-2"
              fraction={fraction}
              label={`${spec.label}: ${Math.round(fraction * 100)}% complete`}
            />
          ))}
      </div>
    </li>
  );
}
