import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

/** Titled surface panel: a rounded, bordered container with an optional uppercase header
 *  bar. Hosts the shot tables and the history list. */
export function Panel({
  title,
  className,
  children,
}: {
  title?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={cn("overflow-hidden rounded-xl border bg-surface-raised", className)}>
      {title && (
        <div className="bg-surface-overlay px-4 py-2 text-xs uppercase tracking-wide text-fg-subtle">
          {title}
        </div>
      )}
      {children}
    </div>
  );
}
