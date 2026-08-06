import type { ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

type Variant = "primary" | "secondary" | "danger" | "ghost";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-accent-strong text-white hover:bg-accent disabled:bg-surface-overlay disabled:text-fg-subtle",
  secondary:
    "border border-border bg-surface-raised text-fg hover:bg-surface-overlay hover:border-border-strong disabled:opacity-50",
  danger: "border border-danger/30 bg-danger/10 text-danger hover:bg-danger/20 disabled:opacity-50",
  ghost: "text-fg-muted hover:text-fg hover:bg-surface-overlay disabled:opacity-50",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
}

export function Button({ variant = "primary", className, ...props }: ButtonProps) {
  return (
    <button
      {...props}
      className={cn(
        "inline-flex items-center justify-center rounded-md px-4 py-2 text-sm font-medium transition disabled:cursor-not-allowed",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60 focus-visible:ring-offset-2 focus-visible:ring-offset-surface",
        VARIANTS[variant],
        className,
      )}
    />
  );
}
