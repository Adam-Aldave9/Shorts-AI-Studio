// The Story tab on the result screen: the synopsis, the script, and the world the shots were
// drawn from — the planning draft, read-only, beside the finished cut.

import { useState } from "react";
import type { ProductionPackage } from "@/api/client";
import { formatDuration } from "@/lib/format";
import { Card, cn } from "@/components/ui";
import { SceneBrowser } from "./SceneBrowser";

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-fg-subtle">{label}</dt>
      <dd className="mt-1 text-sm text-fg-muted">{value}</dd>
    </div>
  );
}

function Synopsis({ pkg }: { pkg: ProductionPackage }) {
  const logline = pkg.narrative?.logline?.trim();
  return (
    <Card className="space-y-5">
      <div>
        <div className="text-xs uppercase tracking-wide text-fg-subtle">Synopsis</div>
        <p className="mt-2 text-lg leading-relaxed text-fg">{logline || pkg.meta.premise}</p>
        {logline && <p className="mt-3 text-sm text-fg-muted">{pkg.meta.premise}</p>}
      </div>
      <dl className="grid grid-cols-2 gap-4 border-t pt-4 sm:grid-cols-4">
        <Detail label="Duration" value={formatDuration(pkg.meta.target_duration_s)} />
        <Detail label="Aspect" value={pkg.meta.aspect_ratio ?? "16:9"} />
        <Detail label="Style" value={pkg.meta.style} />
        <Detail label="Voice" value={pkg.meta.narration_voice_id} />
      </dl>
    </Card>
  );
}

function Entity({ item }: { item: { id: string; name: string; canonical_description: string } }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="border-t pt-3 first:border-t-0 first:pt-0">
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="text-sm font-medium text-fg">{item.name}</span>
        <span className="font-mono text-xs text-fg-subtle">{item.id}</span>
      </div>
      <button
        type="button"
        onClick={() => setExpanded((open) => !open)}
        title={expanded ? "Collapse" : "Expand"}
        className={cn(
          "mt-1 block w-full text-left text-sm leading-relaxed text-fg-muted transition hover:text-fg",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:ring-offset-1 focus-visible:ring-offset-surface",
          !expanded && "line-clamp-2",
        )}
      >
        {item.canonical_description}
      </button>
    </div>
  );
}

function WorldCard({ pkg }: { pkg: ProductionPackage }) {
  const characters = pkg.world?.characters ?? [];
  const locations = pkg.world?.locations ?? [];
  if (characters.length === 0 && locations.length === 0) return null;

  return (
    <Card className="space-y-4">
      <div>
        <div className="text-xs uppercase tracking-wide text-fg-subtle">World</div>
        <p className="mt-1 text-xs text-fg-subtle">
          These descriptions were woven into every shot prompt — the mechanism that keeps the
          cast and sets consistent across shots.
        </p>
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        {characters.length > 0 && (
          <div className="space-y-3">
            <div className="text-xs uppercase tracking-wide text-fg-subtle">
              Cast ({characters.length})
            </div>
            {characters.map((item) => (
              <Entity key={item.id} item={item} />
            ))}
          </div>
        )}
        {locations.length > 0 && (
          <div className="space-y-3">
            <div className="text-xs uppercase tracking-wide text-fg-subtle">
              Locations ({locations.length})
            </div>
            {locations.map((item) => (
              <Entity key={item.id} item={item} />
            ))}
          </div>
        )}
      </div>
    </Card>
  );
}

export function StoryPanel({
  pkg,
  onSeek,
}: {
  pkg: ProductionPackage;
  onSeek: (nodeId: string) => void;
}) {
  return (
    <div className="space-y-4">
      <Synopsis pkg={pkg} />
      <SceneBrowser pkg={pkg} onSeek={onSeek} />
      <WorldCard pkg={pkg} />
    </div>
  );
}
