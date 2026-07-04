// Minimal Tailwind UI primitives for the internal tool (spec §9.1 calls for
// shadcn/ui; these hand-rolled equivalents keep the dependency surface small while
// giving the screens consistent buttons / cards / badges / banners).

import type { ButtonHTMLAttributes, ReactNode } from "react";
import { errorToMessages } from "@/lib/errors";

export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

export const controlClass =
  "w-full rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm " +
  "focus:border-neutral-500 focus:outline-none focus:ring-1 focus:ring-neutral-500";

type Variant = "primary" | "secondary" | "danger" | "ghost";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-neutral-900 text-white hover:bg-neutral-700 disabled:bg-neutral-400",
  secondary: "border border-neutral-300 bg-white text-neutral-800 hover:bg-neutral-100 disabled:opacity-50",
  danger: "border border-red-300 bg-white text-red-700 hover:bg-red-50 disabled:opacity-50",
  ghost: "text-neutral-600 hover:text-neutral-900 disabled:opacity-50",
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
        VARIANTS[variant],
        className,
      )}
    />
  );
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn("rounded-lg border bg-white p-5 shadow-sm", className)}>{children}</div>;
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="text-sm font-medium text-neutral-700">{label}</span>
      {hint && <span className="ml-2 text-xs text-neutral-400">{hint}</span>}
      <div className="mt-1">{children}</div>
    </label>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="rounded-md border bg-white px-4 py-3">
      <div className="text-xs uppercase tracking-wide text-neutral-500">{label}</div>
      <div className="mt-1 text-lg font-semibold tabular-nums text-neutral-900">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-neutral-400">{hint}</div>}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-neutral-500">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-neutral-300 border-t-neutral-600" />
      {label ?? "Loading..."}
    </div>
  );
}

export function ErrorBanner({ title, error }: { title?: string; error: unknown }) {
  const messages = errorToMessages(error);
  return (
    <div className="rounded-md border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800">
      {title && <div className="mb-1 font-semibold">{title}</div>}
      <ul className="list-disc space-y-0.5 pl-5">
        {messages.map((message, index) => (
          <li key={index}>{message}</li>
        ))}
      </ul>
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed bg-white px-6 py-12 text-center">
      <div className="text-sm font-medium text-neutral-700">{title}</div>
      {children && <div className="mt-2 text-sm text-neutral-500">{children}</div>}
    </div>
  );
}

const NODE_COLORS: Record<string, string> = {
  pending: "bg-neutral-100 text-neutral-600 border-neutral-300",
  dispatched: "bg-blue-50 text-blue-700 border-blue-300",
  succeeded: "bg-green-50 text-green-700 border-green-300",
  failed: "bg-red-50 text-red-700 border-red-300",
  "dead-lettered": "bg-rose-100 text-rose-800 border-rose-400",
};

/** A live DAG node's status pill (spec §9.2 Status screen). */
export function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={cn(
        "inline-block rounded-full border px-2 py-0.5 text-xs font-medium",
        NODE_COLORS[status] ?? NODE_COLORS.pending,
      )}
    >
      {status}
    </span>
  );
}

const PHASE_COLORS: Record<string, string> = {
  queued: "bg-neutral-100 text-neutral-600 border-neutral-300",
  executing: "bg-blue-50 text-blue-700 border-blue-300",
  compositing: "bg-indigo-50 text-indigo-700 border-indigo-300",
  complete: "bg-green-50 text-green-700 border-green-300",
  blocked: "bg-amber-50 text-amber-700 border-amber-300",
  paused: "bg-amber-50 text-amber-700 border-amber-300",
};

/** A run's overall phase pill; `null` (not yet started) reads as "queued". */
export function PhaseBadge({ phase }: { phase: string | null }) {
  const label = phase ?? "queued";
  return (
    <span
      className={cn(
        "inline-block rounded-full border px-2.5 py-0.5 text-xs font-medium capitalize",
        PHASE_COLORS[label] ?? PHASE_COLORS.queued,
      )}
    >
      {label}
    </span>
  );
}
