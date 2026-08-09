import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export function WarningBanner({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={cn(
        "rounded-md border border-warning/30 bg-warning/10 px-4 py-3 text-sm text-warning",
        className,
      )}
    >
      {children}
    </div>
  );
}
