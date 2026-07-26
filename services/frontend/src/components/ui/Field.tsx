import type { ReactNode } from "react";

export const controlClass =
  "w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-fg " +
  "placeholder:text-fg-subtle focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent";

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="text-sm font-medium text-fg">{label}</span>
      {hint && <span className="ml-2 text-xs text-fg-subtle">{hint}</span>}
      <div className="mt-1">{children}</div>
    </label>
  );
}
