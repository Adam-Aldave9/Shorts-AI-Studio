// Planning screen: follows an async planning job's SSE progress (world -> script ->
// breakdown -> prompts -> assemble). At every moment it answers three questions - what is
// happening now, how long it has been happening, and what it has produced so far. On
// `succeeded` it dwells briefly on the result, then routes to the checkpoint.

import { useEffect } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, type PlanningEvent } from "@/api/client";
import { usePlanningStream } from "@/hooks/usePlanningStream";
import { useNavigateOnce } from "@/hooks/useNavigateOnce";
import { useNow } from "@/hooks/useNow";
import { formatDuration } from "@/lib/format";
import { Button, Card, ErrorBanner, ProgressBar, Spinner, SuccessBanner } from "@/components/ui";
import { StageRow, type StageState } from "@/components/planning/StageRow";
import { STAGES, detailFraction, renderDetail } from "@/components/planning/stages";

const TOTAL_WEIGHT = STAGES.reduce((sum, stage) => sum + stage.typicalS, 0);

/** An active stage with no `done / total` of its own asymptotes toward its own boundary
 *  rather than ever implying it has finished. */
function activeFraction(event: PlanningEvent, stageElapsedS: number, typicalS: number): number {
  const reported = detailFraction(event.details[event.stage ?? ""]);
  if (reported !== null) return reported;
  return Math.min(0.9, stageElapsedS / typicalS);
}

function overallFraction(event: PlanningEvent, activeIdx: number, stageElapsedS: number): number {
  if (event.status === "succeeded") return 1;
  let weight = 0;
  STAGES.forEach((stage, idx) => {
    if (idx < activeIdx) weight += stage.typicalS;
  });
  const active = STAGES[activeIdx];
  if (active && event.status !== "failed") {
    weight += active.typicalS * activeFraction(event, stageElapsedS, active.typicalS);
  }
  return Math.min(0.99, weight / TOTAL_WEIGHT);
}

function stageState(event: PlanningEvent, idx: number, activeIdx: number): StageState {
  if (event.status === "succeeded") return "done";
  if (idx < activeIdx) return "done";
  // A failed job leaves its stage named but no longer running, so nothing spins.
  if (idx === activeIdx) return event.status === "failed" ? "pending" : "active";
  return "pending";
}

export default function Planning() {
  const { jobId = "" } = useParams();
  const { event, receivedAt, connection } = usePlanningStream(jobId);
  const navigateOnce = useNavigateOnce();
  const now = useNow();

  // `queued` has no stage yet; treat it as the first stage already underway rather than
  // rendering every row as pending (which reads as nothing happening at all).
  const activeIdx = event && event.stage_index >= 0 ? event.stage_index : 0;
  const live = event !== null && event.status !== "succeeded" && event.status !== "failed";
  // Server-computed elapsed, smoothed locally between frames (never `Date.now()` minus a
  // server timestamp - that corrupts under clock skew).
  const sinceFrame = live ? Math.max(0, (now - receivedAt) / 1000) : 0;
  const elapsedS = (event?.elapsed_s ?? 0) + sinceFrame;
  const stageElapsedS = (event?.stage_elapsed_s ?? 0) + sinceFrame;

  const succeeded = event?.status === "succeeded";
  const projectId = event?.project_id ?? "";

  useEffect(() => {
    if (!succeeded || !projectId) return;
    const timer = setTimeout(() => navigateOnce(`/checkpoint/${projectId}`), 1200);
    return () => clearTimeout(timer);
  }, [succeeded, projectId, navigateOnce]);

  // A backgrounded tab still shows how far along the job is.
  useEffect(() => {
    if (!event) return;
    const previous = document.title;
    document.title =
      event.status === "failed"
        ? "Planning failed - AI Film Pipeline"
        : `Planning (${Math.min(activeIdx + 1, STAGES.length)}/${STAGES.length}) - AI Film Pipeline`;
    return () => {
      document.title = previous;
    };
  }, [event, activeIdx]);

  if (!event) return <Spinner label="Connecting to the planning job..." />;

  const failed = event.status === "failed";
  const failedStage = failed ? STAGES[activeIdx] : undefined;
  const overall = overallFraction(event, activeIdx, stageElapsedS);

  const stageList = (
    <Card className="mt-6">
      <ul className="space-y-4" role="list" aria-busy={live}>
        {STAGES.map((spec, idx) => {
          const state = stageState(event, idx, activeIdx);
          return (
            <StageRow
              key={spec.key}
              spec={spec}
              state={state}
              detail={event.details[spec.key]}
              elapsedS={
                state === "active" ? stageElapsedS : (event.stage_timings[spec.key] ?? null)
              }
            />
          );
        })}
      </ul>
    </Card>
  );

  if (failed) {
    return (
      <div className="mx-auto max-w-2xl">
        <h1 className="text-2xl font-semibold">Planning failed</h1>
        <div className="mt-6 space-y-4">
          <ErrorBanner
            title={
              failedStage
                ? `Failed while ${failedStage.label.toLowerCase()}`
                : "The planning chain could not produce a valid package"
            }
            // ApiError's 422 shape is how `errorToMessages` reaches its string-array path.
            error={new ApiError(422, event.errors ?? ["Planning failed"])}
          />
          <Link to="/submit">
            <Button variant="secondary">Back to submit</Button>
          </Link>
        </div>
        {stageList}
        <p className="mt-4 font-mono text-xs text-fg-subtle">{event.job_id}</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-semibold">Planning your film</h1>
          <span className="rounded-full border border-border-strong px-2 py-0.5 text-xs text-fg-muted">
            Stage {Math.min(activeIdx + 1, STAGES.length)} of {STAGES.length}
          </span>
        </div>
        <p className="font-mono text-xs text-fg-subtle">{event.job_id}</p>
      </div>

      <p className="mt-1 text-sm text-fg-muted">
        Compiling the brief into a production package. You can leave this page - the job keeps
        running and the finished package appears in History.
      </p>

      <div className="mt-6 flex items-center gap-3">
        <span className="shrink-0 text-sm tabular-nums text-fg-muted">
          {formatDuration(elapsedS)} elapsed
        </span>
        <ProgressBar
          className="flex-1"
          fraction={overall}
          label={`Planning ${Math.round(overall * 100)}% complete`}
        />
        {connection === "reconnecting" && (
          <span className="shrink-0 text-xs text-warning">Reconnecting...</span>
        )}
      </div>

      <p className="sr-only" aria-live="polite">
        {succeeded
          ? "Planning complete"
          : `Stage ${activeIdx + 1} of ${STAGES.length}: ${STAGES[activeIdx]?.label.toLowerCase()}`}
      </p>

      {stageList}

      {succeeded && (
        <div className="mt-4">
          <SuccessBanner>
            {renderDetail("assemble", event.details.assemble) ?? "Package ready"} - opening the
            checkpoint...{" "}
            {projectId && (
              <Link className="font-medium underline" to={`/checkpoint/${projectId}`}>
                open now
              </Link>
            )}
          </SuccessBanner>
        </div>
      )}
    </div>
  );
}
