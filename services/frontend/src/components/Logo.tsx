// Shared brand mark: the same violet play glyph as the favicon, colored via
// currentColor so callers set the hue with a text-* class. Used by the App header,
// Login/Register, and the landing nav/footer.

import { cn } from "@/components/ui";

export function Logo({
  withWordmark = false,
  className,
}: {
  withWordmark?: boolean;
  className?: string;
}) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <svg
        viewBox="0 0 32 32"
        className="h-6 w-6 text-accent"
        fill="currentColor"
        aria-hidden="true"
      >
        <rect width="32" height="32" rx="7" className="fill-surface-raised" />
        <rect
          x="1"
          y="1"
          width="30"
          height="30"
          rx="6"
          fill="none"
          className="stroke-accent"
          strokeOpacity="0.4"
        />
        <path d="M12 9.5v13l11-6.5z" fill="currentColor" />
      </svg>
      {withWordmark && (
        <span className="font-semibold tracking-tight text-fg">AI Film Pipeline</span>
      )}
    </span>
  );
}
