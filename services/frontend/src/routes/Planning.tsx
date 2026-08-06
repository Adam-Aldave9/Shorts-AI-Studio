// Planning screen: follows an async planning job's SSE progress (world -> script ->
// breakdown -> prompts -> assembling). On `succeeded` it routes to the checkpoint; on
// `failed` it shows the validator/error detail. Modeled on Status.tsx.

import { useEffect } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "@/api/client";
import { usePlanningStream } from "@/hooks/usePlanningStream";
import { useNavigateOnce } from "@/hooks/useNavigateOnce";
import { Button, Card, ErrorBanner, Spinner } from "@/components/ui";

// The chain's stages, in order, with human labels — must match the backend's
// `STAGE_SEQUENCE` (planning/graph.py). Each frame's `stage` is one of these keys.
const STAGES: Array<{ key: string; label: string }> = [
  { key: "world", label: "Building the world (cast & sets)" },
  { key: "script", label: "Writing the script" },
  { key: "breakdown", label: "Breaking down shots" },
  { key: "prompts", label: "Writing shot prompts" },
  { key: "assemble", label: "Assembling & validating package" },
];

type StageState = "done" | "active" | "pending";

function StageRow({ label, status }: { label: string; status: StageState }) {
  const dot =
    status === "done" ? (
      <svg className="h-4 w-4 text-success" viewBox="0 0 16 16" fill="none">
        <path d="M3 8.5l3 3 7-7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      </svg>
    ) : status === "active" ? (
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-surface-overlay border-t-accent" />
    ) : (
      <span className="h-4 w-4 rounded-full border-2 border-border" />
    );
  return (
    <li className="flex items-center gap-3">
      <span className="flex h-4 w-4 items-center justify-center text-xs">{dot}</span>
      <span className={status === "pending" ? "text-sm text-fg-subtle" : "text-sm text-fg"}>
        {label}
      </span>
    </li>
  );
}

export default function Planning() {
  const { jobId = "" } = useParams();
  const event = usePlanningStream(jobId);
  const navigateOnce = useNavigateOnce();

  // On success, hand off to the checkpoint for the freshly-persisted package.
  useEffect(() => {
    if (event?.status === "succeeded" && event.project_id) {
      navigateOnce(`/checkpoint/${event.project_id}`);
    }
  }, [event, navigateOnce]);

  if (!event) return <Spinner label="Starting planning..." />;

  if (event.status === "failed") {
    return (
      <div className="mx-auto max-w-2xl">
        <h1 className="text-2xl font-semibold">Planning failed</h1>
        <div className="mt-6 space-y-4">
          <ErrorBanner
            title="The planning chain could not produce a valid package"
            error={new ApiError(422, event.errors ?? ["Planning failed"])}
          />
          <Link to="/submit">
            <Button variant="secondary">Back to submit</Button>
          </Link>
        </div>
      </div>
    );
  }

  // queued/running: the live stage drives the per-stage checklist.
  const activeIdx = event.stage ? STAGES.findIndex((stage) => stage.key === event.stage) : -1;

  return (
    <div className="mx-auto max-w-2xl">
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-semibold">Planning your film</h1>
        <Spinner />
      </div>
      <p className="mt-1 text-sm text-fg-muted">
        Compiling the brief into a production package. This can take a minute on a real run — you'll
        be taken to the checkpoint the moment it's ready.
      </p>

      <Card className="mt-6">
        <ul className="space-y-3">
          {STAGES.map((stage, idx) => {
            const status: StageState =
              activeIdx < 0
                ? "pending"
                : idx < activeIdx
                  ? "done"
                  : idx === activeIdx
                    ? "active"
                    : "pending";
            return <StageRow key={stage.key} label={stage.label} status={status} />;
          })}
        </ul>
      </Card>

      <p className="mt-4 font-mono text-xs text-fg-subtle">{event.job_id}</p>
    </div>
  );
}
