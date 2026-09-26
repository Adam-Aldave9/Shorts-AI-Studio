// Modal for an AI rewrite: give direction, generate, compare before and after, then accept
// or discard. Modal on purpose, so accepting can replace the draft wholesale.

import { useState, type ReactNode } from "react";
import { useMutation } from "@tanstack/react-query";
import { proposeStory, type Scene } from "@/api/client";
import { normalizeStory, type StoryDraft, type StoryEntity, type StoryShot } from "@/lib/story";
import { Button, ErrorBanner, Field, controlClass } from "@/components/ui";
import type { ProposalConfig } from "./steps";

function Side({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0 space-y-1 rounded-md border border-border bg-surface p-3 text-xs">
      <div className="uppercase tracking-wide text-fg-subtle">{label}</div>
      {children}
    </div>
  );
}

function EntityView({ entity }: { entity: StoryEntity | undefined }) {
  if (!entity) return <p className="text-fg-subtle">(none)</p>;
  return (
    <>
      <p className="font-medium text-fg">{entity.name}</p>
      <p className="whitespace-pre-wrap text-fg-muted">{entity.canonical_description}</p>
    </>
  );
}

function SceneView({ scene }: { scene: Scene | undefined }) {
  if (!scene) return <p className="text-fg-subtle">(none)</p>;
  return (
    <>
      <p className="font-medium text-fg">
        {scene.heading} <span className="font-normal text-fg-subtle">@ {scene.location}</span>
      </p>
      <p className="text-fg-muted">{scene.beat}</p>
      <p className="italic text-fg-muted">{scene.narration}</p>
    </>
  );
}

function ShotsView({ shots }: { shots: StoryShot[] }) {
  if (!shots.length) return <p className="text-fg-subtle">(no shots)</p>;
  return (
    <ol className="list-decimal space-y-0.5 pl-4 text-fg-muted">
      {shots.map((shot) => (
        <li key={shot.id}>
          <span className="text-fg">{shot.shot_type}</span> - {shot.action || "-"}
        </li>
      ))}
    </ol>
  );
}

function Diff({
  stage,
  id,
  before,
  after,
}: {
  stage: ProposalConfig["stage"];
  id: string;
  before: StoryDraft;
  after: StoryDraft;
}) {
  const entities = (story: StoryDraft) => [...story.world.characters, ...story.world.locations];
  let left: ReactNode;
  let right: ReactNode;
  if (stage === "world") {
    left = <EntityView entity={entities(before).find((e) => e.id === id)} />;
    right = <EntityView entity={entities(after).find((e) => e.id === id)} />;
  } else if (stage === "script") {
    left = <SceneView scene={before.script.scenes.find((s) => s.id === id)} />;
    right = <SceneView scene={after.script.scenes.find((s) => s.id === id)} />;
  } else {
    left = <ShotsView shots={before.shots.filter((s) => s.scene_id === id)} />;
    right = <ShotsView shots={after.shots.filter((s) => s.scene_id === id)} />;
  }
  return (
    <div className="space-y-1">
      <div className="font-mono text-xs text-fg-subtle">{id}</div>
      <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
        <Side label="Before">{left}</Side>
        <Side label="After">{right}</Side>
      </div>
    </div>
  );
}

export function ProposalDialog({
  projectId,
  config,
  story,
  onAccept,
  onClose,
}: {
  projectId: string;
  config: ProposalConfig;
  story: StoryDraft;
  onAccept: (story: StoryDraft) => void;
  onClose: () => void;
}) {
  const [notes, setNotes] = useState(config.notes ?? "");
  const mutation = useMutation({
    mutationFn: () =>
      proposeStory(projectId, { stage: config.stage, story, targets: config.targets, notes }),
  });
  const result = mutation.data;
  const proposed = result ? normalizeStory(result.story) : null;

  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center bg-surface/80 p-6 backdrop-blur-sm">
      <div className="flex max-h-[90vh] w-full max-w-3xl flex-col rounded-xl border bg-surface-raised">
        <div className="border-b border-border px-6 py-4">
          <h2 className="text-lg font-semibold">{config.title}</h2>
          <p className="mt-1 text-xs text-fg-subtle">
            Nothing changes until you accept. Accepting replaces your draft with the proposal.
          </p>
        </div>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-6 py-4">
          <Field label="Direction" hint="what should change?">
            <textarea
              className={controlClass}
              rows={3}
              value={notes}
              disabled={mutation.isPending}
              onChange={(event) => setNotes(event.target.value)}
            />
          </Field>
          {mutation.isPending && (
            <p className="text-sm text-fg-muted">Rewriting... this can take up to a minute.</p>
          )}
          {mutation.isError && <ErrorBanner title="The AI rewrite failed" error={mutation.error} />}
          {result && proposed && (
            <div className="space-y-3">
              {result.notes && <p className="text-sm text-fg-muted">{result.notes}</p>}
              {result.changed.length === 0 ? (
                <p className="text-sm text-fg-subtle">The proposal didn&apos;t change anything.</p>
              ) : (
                result.changed.map((id) => (
                  <Diff key={id} stage={config.stage} id={id} before={story} after={proposed} />
                ))
              )}
            </div>
          )}
        </div>
        <div className="flex justify-end gap-2 border-t border-border px-6 py-4">
          <Button variant="ghost" onClick={onClose} disabled={mutation.isPending}>
            {result ? "Discard" : "Cancel"}
          </Button>
          {result ? (
            <>
              <Button
                variant="secondary"
                onClick={() => mutation.mutate()}
                disabled={mutation.isPending}
              >
                Try again
              </Button>
              <Button onClick={() => proposed && onAccept(proposed)} disabled={mutation.isPending}>
                Accept
              </Button>
            </>
          ) : (
            <Button onClick={() => mutation.mutate()} disabled={mutation.isPending}>
              {mutation.isPending ? "Generating..." : "Generate"}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
