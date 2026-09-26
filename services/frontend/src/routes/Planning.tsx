// Planning screen: follows an async planning job's SSE progress (world -> script ->
// breakdown -> prompts -> assemble). At every moment it answers three questions - what is
// happening now, how long it has been happening, and what it has produced so far. On
// `succeeded` it dwells briefly on the result, then routes to the checkpoint. A revision job
// runs on the same screen, with the stages the user's own edits produced shown as skipped.

import { useEffect } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError, type PlanningEvent } from "@/api/client";
import { usePlanningStream } from "@/hooks/usePlanningStream";
import { useNavigateOnce } from "@/hooks/useNavigateOnce";
import { useNow } from "@/hooks/useNow";
import { formatDuration } from "@/lib/format";
import { Button, Card, ErrorBanner, ProgressBar, Spinner, SuccessBanner } from "@/components/ui";
import { StageRow, type StageState } from "@/components/planning/StageRow";
import { STAGES, detailFraction, renderDetail } from "@/components/planning/stages";

/** An active stage with no `done / total` of its own asymptotes toward its own boundary
 *  rather than ever implying it has finished. */
function activeFraction(event: PlanningEvent, stageElapsedS: number, typicalS: number): number {
  const reported = detailFraction(event.details[event.stage ?? ""]);
  if (reported !== null) return reported;
  return Math.min(0.9, stageElapsedS / typicalS);
}

function overallFraction(event: PlanningEvent, activeIdx: number, stageElapsedS: number): number {
  if (event.status === "succeeded") return 1;
  const skipped = new Set(event.skipped ?? []);
  const totalWeight = STAGES.filter((stage) => !skipped.has(stage.key)).reduce(
    (sum, stage) => sum + stage.typicalS,
    0,
  );
  let weight = 0;
  STAGES.forEach((stage, idx) => {
    if (idx < activeIdx && !skipped.has(stage.key)) weight += stage.typicalS;
  });
  const active = STAGES[activeIdx];
  if (active && event.status !== "failed") {
    weight += active.typicalS * activeFraction(event, stageElapsedS, active.typicalS);
  }
  return Math.min(0.99, weight / totalWeight);
}

function stageState(event: PlanningEvent, idx: number, activeIdx: number): StageState {
  if (event.skipped?.includes(STAGES[idx].key)) return "skipped";
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
  const navigate = useNavigate();
  const queryClient = useQueryClient();
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
  const revision = event?.kind === "revision";
  const skipped = new Set(event?.skipped ?? []);
  const runStages = STAGES.filter((stage) => !skipped.has(stage.key));
  const runPosition = Math.max(
    1,
    runStages.findIndex((stage) => stage.key === STAGES[activeIdx]?.key) + 1,
  );
  const title = !revision
    ? "Planning your film"
    : event?.mode === "in_place"
      ? "Updating the draft"
      : "Building your revision";

  useEffect(() => {
    if (!succeeded || !projectId) return;
    // An in-place revision keeps the project id, and the checkpoint pins its package query,
    // so drop every cached view of it before anything can render the old draft.
    for (const key of ["package", "packageStatus", "reuse", "story", "versions"]) {
      queryClient.removeQueries({ queryKey: [key, projectId] });
    }
    const timer = setTimeout(() => navigateOnce(`/checkpoint/${projectId}`), 1200);
    return () => clearTimeout(timer);
  }, [succeeded, projectId, navigateOnce, queryClient]);

  // A backgrounded tab still shows how far along the job is.
  useEffect(() => {
    if (!event) return;
    const previous = document.title;
    document.title =
      event.status === "failed"
        ? "Planning failed - AI Film Pipeline"
        : `Planning (${runPosition}/${runStages.length}) - AI Film Pipeline`;
    return () => {
      document.title = previous;
    };
  }, [event, runPosition, runStages.length]);

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
                state === "active"
                  ? stageElapsedS
                  : state === "skipped"
                    ? null
                    : (event.stage_timings[spec.key] ?? null)
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
        <h1 className="text-2xl font-semibold">
          {revision ? "The revision failed" : "Planning failed"}
        </h1>
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
          {revision ? (
            <Button variant="secondary" onClick={() => navigate(-1)}>
              Back to the editor
            </Button>
          ) : (
            <Link to="/submit">
              <Button variant="secondary">Back to submit</Button>
            </Link>
          )}
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
          <h1 className="text-2xl font-semibold">{title}</h1>
          <span className="rounded-full border border-border-strong px-2 py-0.5 text-xs text-fg-muted">
            Stage {runPosition} of {runStages.length}
          </span>
        </div>
        <p className="font-mono text-xs text-fg-subtle">{event.job_id}</p>
      </div>

      <p className="mt-1 text-sm text-fg-muted">
        {revision
          ? "Regenerating only what your edits affect; everything else carries over unchanged."
          : "Compiling the brief into a production package."}{" "}
        You can leave this page - the job keeps running and the finished package appears in History.
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
          : `Stage ${runPosition} of ${runStages.length}: ${STAGES[activeIdx]?.label.toLowerCase()}`}
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
