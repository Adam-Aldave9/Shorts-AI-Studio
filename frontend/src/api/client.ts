// Typed client for the planning + scheduler services.
//
// Request/response shapes come straight from the OpenAPI-generated types
// (`npm run gen:api` -> planning.d.ts / scheduler.d.ts), so they stay in lockstep
// with the FastAPI/Pydantic models with no manual sync (spec §3.1, §9.1). The one
// hand-typed shape is the SSE status frame: OpenAPI does not describe SSE bodies,
// so `StatusEvent` below is kept in sync by hand against `_status_event` in
// scheduler/scheduler/main.py.

import type { components as PlanningComponents } from "./planning";
import type { components as SchedulerComponents } from "./scheduler";

export const PLANNING_URL = import.meta.env.VITE_PLANNING_URL ?? "http://localhost:8000";
export const SCHEDULER_URL = import.meta.env.VITE_SCHEDULER_URL ?? "http://localhost:8001";

// --- Generated model types, re-exported for the screens to consume ---
export type Brief = PlanningComponents["schemas"]["Brief"];
export type BriefAccepted = PlanningComponents["schemas"]["BriefAccepted"];
export type ProductionPackage = SchedulerComponents["schemas"]["ProductionPackage"];
export type PackageSummary = SchedulerComponents["schemas"]["PackageSummary"];
export type Asset = SchedulerComponents["schemas"]["Asset"];

/** A non-2xx response. `detail` carries the server's `detail` field when present
 *  — for the scheduler's 422 it is the validator's error list, shown inline at
 *  the checkpoint (spec §4.3). */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: unknown,
  ) {
    super(`HTTP ${status}`);
    this.name = "ApiError";
  }
}

async function readError(res: Response): Promise<unknown> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    return body.detail ?? body;
  } catch {
    return res.statusText;
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    throw new ApiError(res.status, await readError(res));
  }
  return (await res.json()) as T;
}

// --- Planning service: Submit + the Monaco JSON schema (spec §9.2) ---

export function submitBrief(brief: Brief): Promise<BriefAccepted> {
  return request<BriefAccepted>(`${PLANNING_URL}/briefs`, {
    method: "POST",
    body: JSON.stringify(brief),
  });
}

export function getPackageSchema(): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>(`${PLANNING_URL}/schema`);
}

// --- Scheduler service: Checkpoint / Status / Result / History (spec §9.2) ---

export function listPackages(): Promise<PackageSummary[]> {
  return request<PackageSummary[]>(`${SCHEDULER_URL}/packages`);
}

export function getPackage(projectId: string): Promise<ProductionPackage> {
  return request<ProductionPackage>(`${SCHEDULER_URL}/packages/${projectId}`);
}

export function updatePackage(
  projectId: string,
  pkg: ProductionPackage,
): Promise<ProductionPackage> {
  return request<ProductionPackage>(`${SCHEDULER_URL}/packages/${projectId}`, {
    method: "PUT",
    body: JSON.stringify(pkg),
  });
}

export function approvePackage(projectId: string): Promise<{ status: string }> {
  return request<{ status: string }>(`${SCHEDULER_URL}/packages/${projectId}/approve`, {
    method: "POST",
  });
}

// --- SSE: live run status for the Status screen ---
//
// Hand-typed against `_status_event` in scheduler/scheduler/main.py: OpenAPI
// cannot describe SSE frame bodies, so this is the one place that needs manual
// sync with the backend.

/** One DAG node's live state within a {@link StatusEvent}. */
export interface SseNode {
  status: string;
  attempts: number;
  error: string | null;
}

/** The `status` SSE frame streamed from `GET /packages/{id}/events`. */
export interface StatusEvent {
  project_id: string;
  phase: string | null;
  cost_usd: number;
  nodes: Record<string, SseNode>;
  critical_path_s: number;
  final_url: string | null;
  complete: boolean;
}

export interface EventsHandlers {
  onStatus: (event: StatusEvent) => void;
  onError?: (event: Event) => void;
}

/**
 * Subscribe to the run's live status stream. Returns the `EventSource` so the
 * caller can `.close()` it on unmount. The backend emits named `status` frames
 * and closes the stream itself once the run reaches a terminal phase, after the
 * compositor has set `final_url`.
 */
export function openEvents(projectId: string, handlers: EventsHandlers): EventSource {
  const source = new EventSource(`${SCHEDULER_URL}/packages/${projectId}/events`);
  source.addEventListener("status", (event) => {
    handlers.onStatus(JSON.parse((event as MessageEvent).data) as StatusEvent);
  });
  if (handlers.onError) {
    source.addEventListener("error", handlers.onError);
  }
  return source;
}
