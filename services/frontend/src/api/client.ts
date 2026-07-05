// Typed client for the planning + scheduler services.
//
// Request/response shapes come straight from the OpenAPI-generated types
// (`npm run gen:api` -> planning.d.ts / scheduler.d.ts), so they stay in lockstep
// with the FastAPI/Pydantic models with no manual sync (spec §3.1, §9.1). The lone
// exception is the SSE status frame, hand-typed below.

import type { components as PlanningComponents } from "./planning";
import type { components as SchedulerComponents } from "./scheduler";

// Same-origin proxy paths by default (nginx in prod, the Vite dev-server proxy in
// dev). Same-origin is what keeps the session cookie first-party.
export const PLANNING_URL = import.meta.env.VITE_PLANNING_URL ?? "/api/planning";
export const SCHEDULER_URL = import.meta.env.VITE_SCHEDULER_URL ?? "/api/scheduler";

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

/** A 401 from any endpoint — the session is missing or expired. The AuthContext
 *  catches this to drop the user back to the login screen. */
export class UnauthorizedError extends ApiError {
  constructor(detail: unknown) {
    super(401, detail);
    this.name = "UnauthorizedError";
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

/** Read a cookie by name (used to echo the readable `afp_csrf` token back in a
 *  header — the double-submit half of the CSRF defense). */
function readCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

const CSRF_COOKIE = "afp_csrf";
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? "GET").toUpperCase();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string> | undefined),
  };
  // Attach the CSRF token on unsafe methods; the server constant-time compares it to
  // the session's token.
  if (!SAFE_METHODS.has(method)) {
    const token = readCookie(CSRF_COOKIE);
    if (token) headers["X-CSRF-Token"] = token;
  }
  const res = await fetch(url, {
    ...init,
    headers,
    credentials: "include", // send the first-party session + csrf cookies
  });
  if (!res.ok) {
    const detail = await readError(res);
    if (res.status === 401) throw new UnauthorizedError(detail);
    throw new ApiError(res.status, detail);
  }
  // 204 No Content (e.g. logout) has no body to parse.
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// --- Auth: register / login / logout / session bootstrap ---
//
// All go through the scheduler origin (either service works — they share the session
// layer), same-origin, credentialed. Login/register set the cookies; the SPA reads
// its auth state from `getMe`.

/** The public view of the signed-in account (matches the backend `UserOut`). */
export interface AuthUser {
  user_id: string;
  username: string;
}

export function register(username: string, password: string): Promise<AuthUser> {
  return request<AuthUser>(`${SCHEDULER_URL}/auth/register`, {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export function login(username: string, password: string): Promise<AuthUser> {
  return request<AuthUser>(`${SCHEDULER_URL}/auth/login`, {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export function logout(): Promise<void> {
  return request<void>(`${SCHEDULER_URL}/auth/logout`, { method: "POST" });
}

export function getMe(): Promise<AuthUser> {
  return request<AuthUser>(`${SCHEDULER_URL}/auth/me`);
}

/** Prime the readable `afp_csrf` cookie for the session (used after a reload). */
export function fetchCsrf(): Promise<{ csrf: string | null }> {
  return request<{ csrf: string | null }>(`${SCHEDULER_URL}/auth/csrf`);
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
  // `withCredentials` sends the session cookie on the SSE connection — EventSource
  // cannot set an Authorization header, which is exactly why the auth model is
  // cookie-based. Same-origin means the cookie flows automatically.
  const source = new EventSource(`${SCHEDULER_URL}/packages/${projectId}/events`, {
    withCredentials: true,
  });
  source.addEventListener("status", (event) => {
    handlers.onStatus(JSON.parse((event as MessageEvent).data) as StatusEvent);
  });
  if (handlers.onError) {
    source.addEventListener("error", handlers.onError);
  }
  return source;
}
