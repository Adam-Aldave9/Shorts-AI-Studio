// Minimal Tailwind UI primitives for the internal tool (spec §9.1 calls for
// shadcn/ui; these hand-rolled equivalents keep the dependency surface small while
// giving the screens consistent buttons / cards / badges / banners). All chrome
// colors go through the design tokens in tailwind.config.js / index.css.

import type { ButtonHTMLAttributes, ReactNode } from "react";
import { errorToMessages } from "@/lib/errors";

export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

export const controlClass =
  "w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-fg " +
  "placeholder:text-fg-subtle focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent";

type Variant = "primary" | "secondary" | "danger" | "ghost";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-accent-strong text-white hover:bg-accent disabled:bg-surface-overlay disabled:text-fg-subtle",
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

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn("rounded-xl border bg-surface-raised p-5", className)}>{children}</div>;
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="text-sm font-medium text-fg">{label}</span>
      {hint && <span className="ml-2 text-xs text-fg-subtle">{hint}</span>}
      <div className="mt-1">{children}</div>
    </label>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="rounded-md border bg-surface-raised px-4 py-3">
      <div className="text-xs uppercase tracking-wide text-fg-subtle">{label}</div>
      <div className="mt-1 text-lg font-semibold tabular-nums text-fg">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-fg-subtle">{hint}</div>}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-fg-muted">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-surface-overlay border-t-accent" />
      {label ?? "Loading..."}
    </div>
  );
}

export function ErrorBanner({ title, error }: { title?: string; error: unknown }) {
  const messages = errorToMessages(error);
  return (
    <div className="rounded-md border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">
      {title && <div className="mb-1 font-semibold">{title}</div>}
      <ul className="list-disc space-y-0.5 pl-5">
        {messages.map((message, index) => (
          <li key={index}>{message}</li>
        ))}
      </ul>
    </div>
  );
}

/** Positive confirmation banner (mirror of ErrorBanner). */
export function SuccessBanner({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-md border border-success/30 bg-success/10 px-4 py-2 text-sm text-success">
      {children}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-border bg-surface-raised/50 px-6 py-12 text-center">
      <div className="text-sm font-medium text-fg">{title}</div>
      {children && <div className="mt-2 text-sm text-fg-muted">{children}</div>}
    </div>
  );
}

// Translucent dark treatment: colored text/border over a ~10% tinted fill. Status
// hues are semantic (executing blue, succeeded green, ...) and stay literal here.
const NODE_COLORS: Record<string, string> = {
  pending: "bg-surface-overlay/60 text-fg-muted border-border",
  dispatched: "bg-blue-500/10 text-blue-300 border-blue-500/30",
  succeeded: "bg-green-500/10 text-green-300 border-green-500/30",
  failed: "bg-red-500/10 text-red-300 border-red-500/30",
  "dead-lettered": "bg-rose-500/15 text-rose-300 border-rose-500/40",
};

// Live states get a pulsing status dot for at-a-glance liveness.
const LIVE_STATES = new Set(["dispatched", "executing", "compositing"]);

function StatusDot({ live }: { live: boolean }) {
  return (
    <span
      className={cn(
        "mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-current",
        live && "animate-pulse",
      )}
    />
  );
}

/** A live DAG node's status pill (spec §9.2 Status screen). */
export function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium",
        NODE_COLORS[status] ?? NODE_COLORS.pending,
      )}
    >
      <StatusDot live={LIVE_STATES.has(status)} />
      {status}
    </span>
  );
}

const PHASE_COLORS: Record<string, string> = {
  queued: "bg-surface-overlay/60 text-fg-muted border-border",
  executing: "bg-blue-500/10 text-blue-300 border-blue-500/30",
  compositing: "bg-indigo-500/10 text-indigo-300 border-indigo-500/30",
  complete: "bg-green-500/10 text-green-300 border-green-500/30",
  blocked: "bg-amber-500/10 text-amber-300 border-amber-500/30",
  paused: "bg-amber-500/10 text-amber-300 border-amber-500/30",
};

/** A run's overall phase pill; `null` (not yet started) reads as "queued". */
export function PhaseBadge({ phase }: { phase: string | null }) {
  const label = phase ?? "queued";
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium capitalize",
        PHASE_COLORS[label] ?? PHASE_COLORS.queued,
      )}
    >
      <StatusDot live={LIVE_STATES.has(label)} />
      {label}
    </span>
  );
}
