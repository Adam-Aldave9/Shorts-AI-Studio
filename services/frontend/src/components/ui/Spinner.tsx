export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-fg-muted">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-surface-overlay border-t-accent" />
      {label ?? "Loading..."}
    </div>
  );
}
