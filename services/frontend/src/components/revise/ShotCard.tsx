// One shot of a scene: its breakdown tags and action. The prompt itself is rewritten by AI
// when these change, and can be fine-tuned at the checkpoint of the resulting version.

import type { Scene } from "@/api/client";
import { SHOT_TYPES, type StoryAction, type StoryDraft, type StoryShot } from "@/lib/story";
import { Button, Card, cn, controlClass } from "@/components/ui";
import { ChangeChip } from "./ChangeChip";

export function ShotCard({
  shot,
  index,
  count,
  draft,
  scenes,
  status,
  currentPrompt,
  dispatch,
}: {
  shot: StoryShot;
  index: number;
  count: number;
  draft: StoryDraft;
  scenes: Scene[];
  status: string | undefined;
  /** The existing shot's prompt in this version; undefined for a new shot. */
  currentPrompt: string | undefined;
  dispatch: (action: StoryAction) => void;
}) {
  const update = (patch: Partial<Omit<StoryShot, "id">>) =>
    dispatch({ type: "updateShot", id: shot.id, patch });
  const types = SHOT_TYPES.includes(shot.shot_type) ? SHOT_TYPES : [shot.shot_type, ...SHOT_TYPES];

  return (
    <Card className="space-y-3 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="tabular-nums text-xs text-fg-subtle">
            {String(index + 1).padStart(2, "0")}
          </span>
          <span className="font-mono text-xs text-fg-muted">{shot.id}</span>
          {currentPrompt === undefined && <ChangeChip status="new" />}
          {status && status !== "kept" && status !== "new" && <ChangeChip status={status} />}
        </div>
        <div className="flex gap-1">
          <Button
            variant="ghost"
            className="px-2 py-1 text-xs"
            disabled={index === 0}
            onClick={() => dispatch({ type: "moveShot", id: shot.id, delta: -1 })}
          >
            Up
          </Button>
          <Button
            variant="ghost"
            className="px-2 py-1 text-xs"
            disabled={index === count - 1}
            onClick={() => dispatch({ type: "moveShot", id: shot.id, delta: 1 })}
          >
            Down
          </Button>
          <Button
            variant="danger"
            className="px-2 py-1 text-xs"
            onClick={() => dispatch({ type: "removeShot", id: shot.id })}
          >
            Remove
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <label className="text-xs text-fg-subtle">
          Type
          <select
            className={cn(controlClass, "mt-1")}
            value={shot.shot_type}
            onChange={(event) => update({ shot_type: event.target.value })}
          >
            {types.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-fg-subtle">
          Seconds
          <input
            className={cn(controlClass, "mt-1")}
            type="number"
            min={0.5}
            max={15}
            step={0.5}
            value={shot.duration_s}
            onChange={(event) => update({ duration_s: Number(event.target.value) })}
          />
        </label>
        <label className="text-xs text-fg-subtle">
          Location
          <select
            className={cn(controlClass, "mt-1")}
            value={shot.location_id}
            onChange={(event) => update({ location_id: event.target.value })}
          >
            {!draft.world.locations.some((l) => l.id === shot.location_id) && (
              <option value={shot.location_id}>{shot.location_id || "(none)"}</option>
            )}
            {draft.world.locations.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-fg-subtle">
          Scene
          <select
            className={cn(controlClass, "mt-1")}
            value={shot.scene_id}
            onChange={(event) => update({ scene_id: event.target.value })}
          >
            {scenes.map((scene) => (
              <option key={scene.id} value={scene.id}>
                {scene.heading || scene.id}
              </option>
            ))}
          </select>
        </label>
      </div>

      {draft.world.characters.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <span className="text-fg-subtle">In frame</span>
          {draft.world.characters.map((character) => {
            const on = shot.subject_ids.includes(character.id);
            return (
              <button
                key={character.id}
                type="button"
                aria-pressed={on}
                className={cn(
                  "rounded-full border px-2 py-0.5 transition",
                  on
                    ? "border-accent bg-accent/15 text-fg"
                    : "border-border text-fg-muted hover:border-border-strong hover:text-fg",
                )}
                onClick={() =>
                  update({
                    subject_ids: on
                      ? shot.subject_ids.filter((id) => id !== character.id)
                      : [...shot.subject_ids, character.id],
                  })
                }
              >
                {character.name || character.id}
              </button>
            );
          })}
        </div>
      )}

      <label className="block text-xs text-fg-subtle">
        Action
        <textarea
          className={cn(controlClass, "mt-1")}
          rows={2}
          value={shot.action}
          onChange={(event) => update({ action: event.target.value })}
        />
      </label>

      {currentPrompt !== undefined && (
        <details className="text-xs text-fg-subtle">
          <summary className="cursor-pointer select-none hover:text-fg-muted">
            Current prompt
          </summary>
          <p className="mt-1 whitespace-pre-wrap rounded bg-surface p-2 text-fg-muted">
            {currentPrompt || "-"}
          </p>
        </details>
      )}
    </Card>
  );
}
