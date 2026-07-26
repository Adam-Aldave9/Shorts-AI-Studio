import type { ReactNode } from "react";

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-border bg-surface-raised/50 px-6 py-12 text-center">
      <div className="text-sm font-medium text-fg">{title}</div>
      {children && <div className="mt-2 text-sm text-fg-muted">{children}</div>}
    </div>
  );
}
