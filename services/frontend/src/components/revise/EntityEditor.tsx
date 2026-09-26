// One character or location: its name and canonical description, where it is used, and
// what changing it will regenerate.

import {
  MAX_DESCRIPTION_CHARS,
  type EntityKind,
  type StoryAction,
  type StoryEntity,
} from "@/lib/story";
import { Button, Card, Field, cn, controlClass } from "@/components/ui";
import { ChangeChip } from "./ChangeChip";
import type { ProposalConfig } from "./steps";

export function EntityEditor({
  entity,
  kind,
  status,
  usedIn,
  dispatch,
  onPropose,
  onRemoved,
}: {
  entity: StoryEntity;
  kind: EntityKind;
  status: string | undefined;
  usedIn: string[];
  dispatch: (action: StoryAction) => void;
  onPropose: (config: ProposalConfig) => void;
  onRemoved: () => void;
}) {
  const length = entity.canonical_description.length;
  const removeBlocked = kind === "location" && usedIn.length > 0;

  return (
    <Card className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs text-fg-subtle">{entity.id}</span>
          {status && <ChangeChip status={status} />}
        </div>
        <div className="flex gap-2">
          <Button
            variant="secondary"
            className="px-3 py-1.5 text-xs"
            onClick={() =>
              onPropose({
                stage: "world",
                targets: [entity.id],
                title: `Rewrite ${entity.name || entity.id} with AI`,
              })
            }
          >
            Rewrite with AI
          </Button>
          <Button
            variant="danger"
            className="px-3 py-1.5 text-xs"
            disabled={removeBlocked}
            title={removeBlocked ? `Used by ${usedIn.length} shots; move them first.` : undefined}
            onClick={() => {
              dispatch({ type: "removeEntity", id: entity.id });
              onRemoved();
            }}
          >
            Remove
          </Button>
        </div>
      </div>
      {removeBlocked && (
        <p className="text-xs text-fg-subtle">
          This location can&apos;t be removed while {usedIn.length}{" "}
          {usedIn.length === 1 ? "shot is" : "shots are"} set there. Move those shots on the Shots
          tab first.
        </p>
      )}

      <Field label="Name">
        <input
          className={controlClass}
          value={entity.name}
          onChange={(event) =>
            dispatch({ type: "updateEntity", id: entity.id, patch: { name: event.target.value } })
          }
        />
      </Field>
      <Field label="Canonical description" hint="woven word for word into every shot it appears in">
        <textarea
          className={controlClass}
          rows={6}
          value={entity.canonical_description}
          onChange={(event) =>
            dispatch({
              type: "updateEntity",
              id: entity.id,
              patch: { canonical_description: event.target.value },
            })
          }
        />
        <div
          className={cn(
            "mt-1 text-right text-xs tabular-nums",
            length > MAX_DESCRIPTION_CHARS ? "text-warning" : "text-fg-subtle",
          )}
        >
          {length}/{MAX_DESCRIPTION_CHARS}
        </div>
      </Field>

      <div className="space-y-1 text-xs">
        <div className="text-fg-subtle">
          {usedIn.length ? `Used in ${usedIn.length} shots` : "Not used in any shot"}
        </div>
        {usedIn.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {usedIn.map((shotId) => (
              <span
                key={shotId}
                className="rounded border border-border bg-surface px-1.5 py-0.5 font-mono text-[11px] text-fg-muted"
              >
                {shotId}
              </span>
            ))}
          </div>
        )}
        <p className="pt-1 text-fg-muted">
          Changing {entity.name || "this entity"} re-renders its reference image and rewrites the{" "}
          {usedIn.length} {usedIn.length === 1 ? "shot" : "shots"} it appears in.
        </p>
      </div>
    </Card>
  );
}
