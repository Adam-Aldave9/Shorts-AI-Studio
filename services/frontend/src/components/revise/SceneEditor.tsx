// One scene: where it plays, what the viewer sees, what is spoken over it.

import { useState } from "react";
import type { Scene } from "@/api/client";
import type { StoryAction, StoryDraft } from "@/lib/story";
import { Button, Card, Field, controlClass } from "@/components/ui";
import { ChangeChip } from "./ChangeChip";
import type { ProposalConfig } from "./steps";

export function SceneEditor({
  scene,
  index,
  total,
  draft,
  status,
  stale,
  shotCount,
  dispatch,
  onPropose,
  onAddAfter,
  onRemoved,
}: {
  scene: Scene;
  index: number;
  total: number;
  draft: StoryDraft;
  status: string | undefined;
  stale: boolean;
  shotCount: number;
  dispatch: (action: StoryAction) => void;
  onPropose: (config: ProposalConfig) => void;
  onAddAfter: () => void;
  onRemoved: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const update = (patch: Partial<Omit<Scene, "id">>) =>
    dispatch({ type: "updateScene", id: scene.id, patch });
  const names = draft.world.locations.map((l) => l.name);
  const matched = names.some((n) => n.trim().toLowerCase() === scene.location.trim().toLowerCase());

  return (
    <Card className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs text-fg-subtle">{scene.id}</span>
          {status && <ChangeChip status={status} />}
          {stale && <ChangeChip status="stale" />}
          <span className="text-xs text-fg-subtle">{shotCount} shots</span>
        </div>
        <div className="flex flex-wrap gap-1">
          <Button
            variant="ghost"
            className="px-2 py-1 text-xs"
            disabled={index === 0}
            onClick={() => dispatch({ type: "moveScene", id: scene.id, delta: -1 })}
          >
            Move up
          </Button>
          <Button
            variant="ghost"
            className="px-2 py-1 text-xs"
            disabled={index === total - 1}
            onClick={() => dispatch({ type: "moveScene", id: scene.id, delta: 1 })}
          >
            Move down
          </Button>
          <Button variant="ghost" className="px-2 py-1 text-xs" onClick={onAddAfter}>
            Add scene after
          </Button>
          <Button
            variant="secondary"
            className="px-2 py-1 text-xs"
            onClick={() =>
              onPropose({
                stage: "script",
                targets: [scene.id],
                title: `Rewrite scene "${scene.heading}" with AI`,
              })
            }
          >
            Rewrite scene with AI
          </Button>
          <Button
            variant="danger"
            className="px-2 py-1 text-xs"
            disabled={total === 1}
            onClick={() => setConfirming(true)}
          >
            Remove
          </Button>
        </div>
      </div>
      {confirming && (
        <div className="flex flex-wrap items-center gap-2 rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger">
          Remove this scene and its {shotCount} {shotCount === 1 ? "shot" : "shots"}?
          <Button
            variant="danger"
            className="px-2 py-1 text-xs"
            onClick={() => {
              dispatch({ type: "removeScene", id: scene.id });
              onRemoved();
            }}
          >
            Remove scene
          </Button>
          <Button
            variant="ghost"
            className="px-2 py-1 text-xs"
            onClick={() => setConfirming(false)}
          >
            Cancel
          </Button>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Heading">
          <input
            className={controlClass}
            value={scene.heading}
            onChange={(event) => update({ heading: event.target.value })}
          />
        </Field>
        <Field label="Location">
          <select
            className={controlClass}
            value={scene.location}
            onChange={(event) => update({ location: event.target.value })}
          >
            {!matched && <option value={scene.location}>{scene.location || "(none)"}</option>}
            {names.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <Field label="What you see" hint="the visual beat">
        <textarea
          className={controlClass}
          rows={3}
          value={scene.beat}
          onChange={(event) => update({ beat: event.target.value })}
        />
      </Field>
      <Field label="What you hear" hint="voiceover narration">
        <textarea
          className={controlClass}
          rows={4}
          value={scene.narration}
          onChange={(event) => update({ narration: event.target.value })}
        />
      </Field>
    </Card>
  );
}
