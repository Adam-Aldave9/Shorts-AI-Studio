// The Script tab: title and logline, then the scenes in a rail with one edited beside it.

import { useState } from "react";
import type { RevisionPreview } from "@/api/client";
import { nextSceneId, shotsOfScene, type StoryAction, type StoryDraft } from "@/lib/story";
import { Button, Card, EmptyState, Field, WarningBanner, cn, controlClass } from "@/components/ui";
import { ChangeDot } from "./ChangeChip";
import { SceneEditor } from "./SceneEditor";
import type { ProposalConfig } from "./steps";

export function ScriptStep({
  draft,
  preview,
  narrationDiverged,
  dispatch,
  onPropose,
}: {
  draft: StoryDraft;
  preview: RevisionPreview | null;
  narrationDiverged: boolean;
  dispatch: (action: StoryAction) => void;
  onPropose: (config: ProposalConfig) => void;
}) {
  const scenes = draft.script.scenes;
  const [selectedId, setSelectedId] = useState<string | null>(scenes[0]?.id ?? null);
  const status = preview?.scene_status ?? {};
  const stale = new Set(preview?.stale_scenes ?? []);
  const selectedIndex = scenes.findIndex((s) => s.id === selectedId);
  const selected = scenes[selectedIndex] ?? null;

  function addAfter(afterId: string | null) {
    const id = nextSceneId(draft);
    const location = draft.world.locations[0]?.name ?? "";
    dispatch({
      type: "addScene",
      afterId,
      scene: { id, heading: "New scene", location, beat: "", narration: "" },
    });
    setSelectedId(id);
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-fg-muted">
          Scenes you change are re-planned into shots by AI when you create the revision, unless you
          edit their shots yourself.
        </p>
        <Button
          variant="secondary"
          onClick={() =>
            onPropose({ stage: "script", targets: [], title: "Rewrite the script with AI" })
          }
        >
          Rewrite script with AI
        </Button>
      </div>
      {narrationDiverged && (
        <WarningBanner>
          The spoken narration was edited at the checkpoint. Editing any scene&apos;s narration here
          replaces the spoken text with the scenes&apos; narration.
        </WarningBanner>
      )}
      <Card className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Title">
          <input
            className={controlClass}
            value={draft.script.title}
            onChange={(event) =>
              dispatch({ type: "setScript", field: "title", value: event.target.value })
            }
          />
        </Field>
        <Field label="Logline">
          <input
            className={controlClass}
            value={draft.script.logline}
            onChange={(event) =>
              dispatch({ type: "setScript", field: "logline", value: event.target.value })
            }
          />
        </Field>
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(220px,280px)_minmax(0,1fr)]">
        <div className="max-h-[70vh] overflow-y-auto rounded-xl border bg-surface-raised">
          {scenes.map((scene, index) => (
            <button
              key={scene.id}
              type="button"
              onClick={() => setSelectedId(scene.id)}
              className={cn(
                "block w-full border-l-2 border-b border-b-border px-3 py-2 text-left transition",
                scene.id === selected?.id
                  ? "border-l-accent bg-surface-overlay"
                  : "border-l-transparent hover:bg-surface-overlay/50",
              )}
            >
              <div className="flex items-center gap-2">
                <span className="tabular-nums text-xs text-fg-subtle">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <span className="truncate text-sm text-fg">{scene.heading || scene.id}</span>
                <span className="ml-auto flex items-center gap-1">
                  <ChangeDot status={status[scene.id]} />
                  {stale.has(scene.id) && <ChangeDot status="stale" />}
                </span>
              </div>
              <div className="text-xs text-fg-subtle">
                {shotsOfScene(draft, scene.id).length} shots
              </div>
            </button>
          ))}
          <button
            type="button"
            onClick={() => addAfter(null)}
            className="block w-full px-3 py-2 text-left text-xs text-accent-soft hover:bg-surface-overlay/50 hover:text-accent"
          >
            + Add scene
          </button>
        </div>
        {selected ? (
          <SceneEditor
            key={selected.id}
            scene={selected}
            index={selectedIndex}
            total={scenes.length}
            draft={draft}
            status={status[selected.id]}
            stale={stale.has(selected.id)}
            shotCount={shotsOfScene(draft, selected.id).length}
            dispatch={dispatch}
            onPropose={onPropose}
            onAddAfter={() => addAfter(selected.id)}
            onRemoved={() => setSelectedId(null)}
          />
        ) : (
          <EmptyState title="Nothing selected">Pick a scene to edit it.</EmptyState>
        )}
      </div>
    </div>
  );
}
