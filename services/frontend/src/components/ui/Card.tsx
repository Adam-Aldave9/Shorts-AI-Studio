import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn("rounded-xl border bg-surface-raised p-5", className)}>{children}</div>;
}
