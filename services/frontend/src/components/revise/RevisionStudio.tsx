// The Revision Studio: go back to any planning stage of a version, edit it directly or with
// reviewed AI proposals, then create a revision that regenerates only what the edits affect.
// All editing is client-side until Create; the server's preview does the change analysis.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useBeforeUnload, useBlocker, useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { createRevision, type RevisionRequest, type StoryResponse } from "@/api/client";
import { useRevisionPreview } from "@/hooks/useRevisionPreview";
import { useStoryDraft } from "@/hooks/useStoryDraft";
import { normalizeStory, type StoryDraft } from "@/lib/story";
import { Button, ErrorBanner, Tabs } from "@/components/ui";
import { BriefStep } from "./BriefStep";
import { ProposalDialog } from "./ProposalDialog";
import { ReviewStep } from "./ReviewStep";
import { ScriptStep } from "./ScriptStep";
import { ShotsStep } from "./ShotsStep";
import { StudioHeader } from "./StudioHeader";
import { WorldStep } from "./WorldStep";
import { STUDIO_STEPS, type ProposalConfig, type StudioStep } from "./steps";

const BRIEF_FIELDS = ["premise", "target_duration_s", "style", "narration_voice_id"] as const;
const HAND_EDITS = new Set(["edited", "new", "removed"]);

function briefChanges(draft: StoryDraft, base: StoryDraft): number {
  return BRIEF_FIELDS.filter((field) => draft.brief[field] !== base.brief[field]).length;
}

export default function RevisionStudio({
  projectId,
  view,
}: {
  projectId: string;
  view: StoryResponse;
}) {
  const navigate = useNavigate();
  const base = useMemo(() => normalizeStory(view.story), [view.story]);
  const { draft, dirty, dispatch } = useStoryDraft(base);
  const [step, setStep] = useState<StudioStep>("brief");
  const [keepShots, setKeepShots] = useState<string[]>([]);
  const [note, setNote] = useState("");
  const [proposal, setProposal] = useState<ProposalConfig | null>(null);
  // Create navigates on its own; the nav guard must not block it.
  const creatingRef = useRef(false);
  const inPlace = view.mode === "in_place";

  const request: RevisionRequest = {
    story: draft,
    keep_shots: keepShots,
    base_hash: view.base_hash,
  };
  const {
    preview,
    error: previewError,
    loading: previewing,
  } = useRevisionPreview(projectId, request);

  const create = useMutation({
    mutationFn: () => createRevision(projectId, { ...request, note: note.trim() }),
    onSuccess: (accepted) => navigate(`/planning/${accepted.job_id}`),
    onError: () => {
      creatingRef.current = false;
    },
  });

  const canCreate =
    preview !== null && preview.errors.length === 0 && (!inPlace || preview.has_changes);

  function onCreate() {
    if (!canCreate || create.isPending) return;
    creatingRef.current = true;
    create.mutate();
  }

  function onDiscard() {
    // react-router keeps an index in history state; with nothing to go back to, fall back
    // to the screen the studio was opened from.
    const idx = (window.history.state as { idx?: number } | null)?.idx ?? 0;
    if (idx > 0) navigate(-1);
    else navigate(inPlace ? `/checkpoint/${projectId}` : `/result/${projectId}`);
  }

  function toggleKeep(sceneId: string) {
    setKeepShots((prev) =>
      prev.includes(sceneId) ? prev.filter((id) => id !== sceneId) : [...prev, sceneId],
    );
  }

  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      dirty && !creatingRef.current && currentLocation.pathname !== nextLocation.pathname,
  );
  useBeforeUnload(
    useCallback(
      (event: BeforeUnloadEvent) => {
        if (dirty && !creatingRef.current) event.preventDefault();
      },
      [dirty],
    ),
  );
  useEffect(() => {
    if (blocker.state === "blocked" && !dirty) blocker.reset?.();
  }, [blocker, dirty]);

  const badge = (n: number) => (n > 0 ? n : undefined);
  const shotStatuses = Object.values(preview?.shot_status ?? {});
  const titleOrLogline =
    Number(draft.script.title !== base.script.title) +
    Number(draft.script.logline !== base.script.logline);
  const tabs = STUDIO_STEPS.map((s) => ({
    ...s,
    badge: badge(
      s.id === "brief"
        ? briefChanges(draft, base)
        : s.id === "world"
          ? Object.keys(preview?.entity_status ?? {}).length
          : s.id === "script"
            ? Object.keys(preview?.scene_status ?? {}).length + titleOrLogline
            : s.id === "shots"
              ? shotStatuses.filter((st) => HAND_EDITS.has(st)).length +
                (preview?.stale_scenes.length ?? 0)
              : (preview?.changes.length ?? 0),
    ),
  }));

  return (
    <div>
      <div className="sticky top-[calc(theme(spacing.header)+1px)] z-10 -mx-6 border-b border-border bg-surface/95 px-6 pb-3 backdrop-blur">
        <StudioHeader
          title={base.script.title}
          projectId={projectId}
          inPlace={inPlace}
          preview={preview}
          previewing={previewing}
          canCreate={canCreate}
          creating={create.isPending}
          onDiscard={onDiscard}
          onCreate={onCreate}
        />
        <Tabs className="mt-3 max-w-2xl" tabs={tabs} active={step} onChange={setStep} />
      </div>

      <div className="mt-4 space-y-2 empty:hidden">
        {previewError != null && (
          <ErrorBanner title="Could not analyse the changes" error={previewError} />
        )}
        {create.isError && (
          <ErrorBanner title="Could not start the revision" error={create.error} />
        )}
      </div>

      <div className="mt-4">
        {step === "brief" && (
          <BriefStep draft={draft} base={base} dispatch={dispatch} onPropose={setProposal} />
        )}
        {step === "world" && (
          <WorldStep draft={draft} preview={preview} dispatch={dispatch} onPropose={setProposal} />
        )}
        {step === "script" && (
          <ScriptStep
            draft={draft}
            preview={preview}
            narrationDiverged={view.narration_diverged}
            dispatch={dispatch}
            onPropose={setProposal}
          />
        )}
        {step === "shots" && (
          <ShotsStep
            draft={draft}
            preview={preview}
            prompts={view.prompts}
            keepShots={keepShots}
            onToggleKeep={toggleKeep}
            dispatch={dispatch}
            onPropose={setProposal}
          />
        )}
        {step === "review" && (
          <ReviewStep
            preview={preview}
            inPlace={inPlace}
            note={note}
            onNote={setNote}
            canCreate={canCreate}
            creating={create.isPending}
            onCreate={onCreate}
          />
        )}
      </div>

      {proposal && (
        <ProposalDialog
          projectId={projectId}
          config={proposal}
          story={draft}
          onAccept={(story) => {
            dispatch({ type: "replace", story });
            setProposal(null);
          }}
          onClose={() => setProposal(null)}
        />
      )}

      {blocker.state === "blocked" && (
        <div className="fixed inset-0 z-20 flex items-center justify-center bg-surface/80 p-6 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-xl border bg-surface-raised p-6">
            <h2 className="text-lg font-semibold">Discard this revision?</h2>
            <p className="mt-2 text-sm text-fg-muted">
              Your edits live only in this editor until you create the revision. Leaving now throws
              them away.
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <Button variant="secondary" onClick={() => blocker.reset?.()}>
                Keep editing
              </Button>
              <Button variant="danger" onClick={() => blocker.proceed?.()}>
                Discard and leave
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
