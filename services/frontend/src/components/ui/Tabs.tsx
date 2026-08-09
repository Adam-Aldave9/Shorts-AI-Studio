import { cn } from "@/lib/cn";

export function Tabs<T extends string>({
  tabs,
  active,
  onChange,
  className,
}: {
  tabs: ReadonlyArray<{ id: T; label: string; badge?: number | string }>;
  active: T;
  onChange: (id: T) => void;
  className?: string;
}) {
  return (
    <div
      role="tablist"
      className={cn(
        "flex items-center gap-1 rounded-md border border-border bg-surface-raised p-1 text-sm",
        className,
      )}
    >
      {tabs.map((tab) => {
        const selected = tab.id === active;
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={selected}
            className={cn(
              "flex-1 rounded px-3 py-1.5 font-medium transition",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:ring-offset-1 focus-visible:ring-offset-surface",
              selected ? "bg-surface-overlay text-fg" : "text-fg-muted hover:text-fg",
            )}
            onClick={() => onChange(tab.id)}
          >
            {tab.label}
            {tab.badge != null && (
              <span className="ml-1.5 tabular-nums text-fg-subtle">{tab.badge}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}
