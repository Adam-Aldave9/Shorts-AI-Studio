// The Shots tab: a scene rail, and the selected scene's shots as editable cards. A scene
// whose content changed but whose shots weren't touched is flagged for AI re-planning.

import { useState } from "react";
import type { RevisionPreview } from "@/api/client";
import {
  locationForScene,
  newShotId,
  shotsOfScene,
  type StoryAction,
  type StoryDraft,
} from "@/lib/story";
import { Button, EmptyState, WarningBanner, cn } from "@/components/ui";
import { ChangeDot } from "./ChangeChip";
import { ShotCard } from "./ShotCard";
import type { ProposalConfig } from "./steps";

export function ShotsStep({
  draft,
  preview,
  prompts,
  keepShots,
  onToggleKeep,
  dispatch,
  onPropose,
}: {
  draft: StoryDraft;
  preview: RevisionPreview | null;
  prompts: Record<string, string>;
  keepShots: string[];
  onToggleKeep: (sceneId: string) => void;
  dispatch: (action: StoryAction) => void;
  onPropose: (config: ProposalConfig) => void;
}) {
  const scenes = draft.script.scenes;
  const [selectedId, setSelectedId] = useState<string | null>(scenes[0]?.id ?? null);
  const scene = scenes.find((s) => s.id === selectedId) ?? scenes[0] ?? null;
  const stale = new Set(preview?.stale_scenes ?? []);
  const shotStatus = preview?.shot_status ?? {};
  const shots = scene ? shotsOfScene(draft, scene.id) : [];

  function addShot() {
    if (!scene) return;
    dispatch({
      type: "addShot",
      shot: {
        id: newShotId(draft),
        scene_id: scene.id,
        shot_type: "wide",
        duration_s: 3.5,
        location_id: shots[shots.length - 1]?.location_id ?? locationForScene(draft, scene),
        subject_ids: [],
        action: "",
      },
    });
  }

  if (!scene)
    return <EmptyState title="No scenes">Add a scene on the Script tab first.</EmptyState>;

  const replan = () =>
    onPropose({
      stage: "shots",
      targets: [scene.id],
      title: `Re-plan the shots of "${scene.heading}"`,
    });

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(220px,280px)_minmax(0,1fr)]">
      <div className="max-h-[75vh] overflow-y-auto rounded-xl border bg-surface-raised">
        {scenes.map((s, index) => (
          <button
            key={s.id}
            type="button"
            onClick={() => setSelectedId(s.id)}
            className={cn(
              "block w-full border-l-2 border-b border-b-border px-3 py-2 text-left transition",
              s.id === scene.id
                ? "border-l-accent bg-surface-overlay"
                : "border-l-transparent hover:bg-surface-overlay/50",
            )}
          >
            <div className="flex items-center gap-2">
              <span className="tabular-nums text-xs text-fg-subtle">
                {String(index + 1).padStart(2, "0")}
              </span>
              <span className="truncate text-sm text-fg">{s.heading || s.id}</span>
              <span className="ml-auto">{stale.has(s.id) && <ChangeDot status="stale" />}</span>
            </div>
            <div className="text-xs text-fg-subtle">{shotsOfScene(draft, s.id).length} shots</div>
          </button>
        ))}
      </div>

      <div className="space-y-3">
        {stale.has(scene.id) && (
          <WarningBanner className="flex flex-wrap items-center gap-2">
            <span className="flex-1">
              {shots.length === 0
                ? "This scene has no shots yet; AI will plan them when you create the revision."
                : "This scene changed; its shots will be re-planned by AI when you create the revision."}
            </span>
            <Button variant="secondary" className="px-2 py-1 text-xs" onClick={replan}>
              Re-plan now
            </Button>
            {shots.length > 0 && (
              <Button
                variant="ghost"
                className="px-2 py-1 text-xs"
                onClick={() => onToggleKeep(scene.id)}
              >
                Keep current shots
              </Button>
            )}
          </WarningBanner>
        )}
        {keepShots.includes(scene.id) && (
          <div className="flex items-center gap-2 rounded-md border border-border bg-surface-raised px-3 py-2 text-xs text-fg-muted">
            Keeping this scene&apos;s current shots even though the scene changed.
            <Button
              variant="ghost"
              className="px-2 py-1 text-xs"
              onClick={() => onToggleKeep(scene.id)}
            >
              Undo
            </Button>
          </div>
        )}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-sm font-semibold">{scene.heading}</h2>
            <p className="text-xs text-fg-subtle">{scene.beat}</p>
          </div>
          {!stale.has(scene.id) && (
            <Button variant="secondary" className="px-3 py-1.5 text-xs" onClick={replan}>
              Re-plan with AI
            </Button>
          )}
        </div>
        {shots.map((shot, index) => (
          <ShotCard
            key={shot.id}
            shot={shot}
            index={index}
            count={shots.length}
            draft={draft}
            scenes={scenes}
            status={shotStatus[shot.id]}
            currentPrompt={prompts[shot.id]}
            dispatch={dispatch}
          />
        ))}
        <Button variant="secondary" onClick={addShot}>
          Add shot
        </Button>
      </div>
    </div>
  );
}
