import { cn } from "@/lib/cn";

export function VersionBadge({ version, className }: { version: number; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border border-accent/40 bg-accent/10 px-2 py-0.5 text-xs font-medium tabular-nums text-accent-soft",
        className,
      )}
    >
      v{version}
    </span>
  );
}
