// The World tab: the cast and locations in a rail, one entity edited beside it.

import { useMemo, useState } from "react";
import type { RevisionPreview } from "@/api/client";
import {
  entityUsage,
  newEntityId,
  type EntityKind,
  type StoryAction,
  type StoryDraft,
  type StoryEntity,
} from "@/lib/story";
import { Button, EmptyState, cn } from "@/components/ui";
import { ChangeDot } from "./ChangeChip";
import { EntityEditor } from "./EntityEditor";
import type { ProposalConfig } from "./steps";

function RailSection({
  title,
  entities,
  selectedId,
  usage,
  status,
  onSelect,
  onAdd,
  addLabel,
}: {
  title: string;
  entities: StoryEntity[];
  selectedId: string | null;
  usage: Map<string, string[]>;
  status: Record<string, string>;
  onSelect: (id: string) => void;
  onAdd: () => void;
  addLabel: string;
}) {
  return (
    <div>
      <div className="bg-surface-overlay px-3 py-1.5 text-xs uppercase tracking-wide text-fg-subtle">
        {title}
      </div>
      {entities.map((entity) => (
        <button
          key={entity.id}
          type="button"
          onClick={() => onSelect(entity.id)}
          className={cn(
            "block w-full border-l-2 border-b border-b-border px-3 py-2 text-left transition",
            entity.id === selectedId
              ? "border-l-accent bg-surface-overlay"
              : "border-l-transparent hover:bg-surface-overlay/50",
          )}
        >
          <div className="flex items-center gap-2">
            <span className="truncate text-sm text-fg">{entity.name || entity.id}</span>
            <span className="ml-auto flex items-center gap-2">
              <ChangeDot status={status[entity.id]} />
            </span>
          </div>
          <div className="text-xs text-fg-subtle">in {usage.get(entity.id)?.length ?? 0} shots</div>
        </button>
      ))}
      <button
        type="button"
        onClick={onAdd}
        className="block w-full border-b border-b-border px-3 py-2 text-left text-xs text-accent-soft hover:bg-surface-overlay/50 hover:text-accent"
      >
        + {addLabel}
      </button>
    </div>
  );
}

export function WorldStep({
  draft,
  preview,
  dispatch,
  onPropose,
}: {
  draft: StoryDraft;
  preview: RevisionPreview | null;
  dispatch: (action: StoryAction) => void;
  onPropose: (config: ProposalConfig) => void;
}) {
  const { characters, locations } = draft.world;
  const [selectedId, setSelectedId] = useState<string | null>(
    characters[0]?.id ?? locations[0]?.id ?? null,
  );
  const usage = useMemo(() => entityUsage(draft), [draft]);
  const status = preview?.entity_status ?? {};

  const selected =
    characters.find((c) => c.id === selectedId) ?? locations.find((l) => l.id === selectedId);
  const kind: EntityKind = characters.some((c) => c.id === selected?.id) ? "character" : "location";

  function add(kindToAdd: EntityKind) {
    const name = kindToAdd === "character" ? "New character" : "New location";
    const id = newEntityId(draft, kindToAdd, name);
    dispatch({
      type: "addEntity",
      kind: kindToAdd,
      entity: { id, name, canonical_description: "", reference_image_ids: [] },
    });
    setSelectedId(id);
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-fg-muted">
          The fixed cast and set. Each description is woven into the prompt of every shot that shows
          it.
        </p>
        <Button
          variant="secondary"
          onClick={() =>
            onPropose({ stage: "world", targets: [], title: "Rewrite the world with AI" })
          }
        >
          Rewrite world with AI
        </Button>
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(220px,280px)_minmax(0,1fr)]">
        <div className="max-h-[70vh] overflow-y-auto rounded-xl border bg-surface-raised">
          <RailSection
            title="Cast"
            entities={characters}
            selectedId={selected?.id ?? null}
            usage={usage}
            status={status}
            onSelect={setSelectedId}
            onAdd={() => add("character")}
            addLabel="Add character"
          />
          <RailSection
            title="Locations"
            entities={locations}
            selectedId={selected?.id ?? null}
            usage={usage}
            status={status}
            onSelect={setSelectedId}
            onAdd={() => add("location")}
            addLabel="Add location"
          />
        </div>
        {selected ? (
          <EntityEditor
            key={selected.id}
            entity={selected}
            kind={kind}
            status={status[selected.id]}
            usedIn={usage.get(selected.id) ?? []}
            dispatch={dispatch}
            onPropose={onPropose}
            onRemoved={() => setSelectedId(null)}
          />
        ) : (
          <EmptyState title="Nothing selected">Pick a character or location to edit it.</EmptyState>
        )}
      </div>
    </div>
  );
}
