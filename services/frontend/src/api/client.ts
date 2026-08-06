// Typed client for the planning + scheduler services. Request/response shapes come from
// the OpenAPI-generated types (`npm run gen:api`), so they track the FastAPI models with
// no manual sync; the SSE frames below are the one hand-typed exception.

import type { components as PlanningComponents } from "./planning";
import type { components as SchedulerComponents } from "./scheduler";

// Same-origin proxy paths (nginx in prod, the Vite dev proxy in dev) keep the session
// cookie first-party.
const PLANNING_URL = import.meta.env.VITE_PLANNING_URL ?? "/api/planning";
const SCHEDULER_URL = import.meta.env.VITE_SCHEDULER_URL ?? "/api/scheduler";

export type Brief = PlanningComponents["schemas"]["Brief"];
export type ProductionPackage = SchedulerComponents["schemas"]["ProductionPackage"];
export type PackageSummary = SchedulerComponents["schemas"]["PackageSummary"];
export type Asset = SchedulerComponents["schemas"]["Asset"];

/** A non-2xx response. For the scheduler's 422, `detail` is the validator's error list,
 *  rendered inline at the checkpoint. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: unknown,
  ) {
    super(`HTTP ${status}`);
    this.name = "ApiError";
  }
}

/** A 401 from any endpoint — the session is missing or expired. AuthContext catches this
 *  to drop the user back to the login screen. */
export class UnauthorizedError extends ApiError {
  constructor(detail: unknown) {
    super(401, detail);
    this.name = "UnauthorizedError";
  }
}

/** The scheduler's edit-lock conflict: the run has started, so PUT/approve return 409. */
export function isConflict(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409;
}

async function readError(res: Response): Promise<unknown> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    return body.detail ?? body;
  } catch {
    return res.statusText;
  }
}

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
  // Double-submit CSRF: echo the readable `afp_csrf` cookie back in a header on unsafe
  // methods; the server constant-time compares it to the session's token.
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
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** The signed-in account (matches the backend `UserOut`). */
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

/** The 202 body from `POST /briefs`: planning runs as an async job the client follows
 *  over SSE. Hand-typed like the SSE frames. */
interface PlanningJobAccepted {
  job_id: string;
}

export function submitBrief(brief: Brief): Promise<PlanningJobAccepted> {
  return request<PlanningJobAccepted>(`${PLANNING_URL}/briefs`, {
    method: "POST",
    body: JSON.stringify(brief),
  });
}

export function getPackageSchema(): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>(`${PLANNING_URL}/schema`);
}

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

/** Editability of a package. `approved` is the authoritative edit lock: once true the run
 *  has started and PUT/approve return 409. */
interface PackageStatus {
  project_id: string;
  approved: boolean;
  phase: string | null;
}

export function getPackageStatus(projectId: string): Promise<PackageStatus> {
  return request<PackageStatus>(`${SCHEDULER_URL}/packages/${projectId}/status`);
}

// SSE frame bodies can't be described by OpenAPI, so the shapes below are hand-typed
// against the backend emitters and must be kept in sync with them.

interface SseHandlers<T> {
  onStatus: (event: T) => void;
  onError?: (event: Event) => void;
}

// `withCredentials` sends the session cookie on the SSE connection — EventSource cannot
// set an Authorization header, which is why the auth model is cookie-based. The backend
// emits named `status` frames and closes the stream itself at a terminal state.
function openSse<T>(url: string, handlers: SseHandlers<T>): EventSource {
  const source = new EventSource(url, { withCredentials: true });
  source.addEventListener("status", (event) => {
    handlers.onStatus(JSON.parse((event as MessageEvent).data) as T);
  });
  if (handlers.onError) source.addEventListener("error", handlers.onError);
  return source;
}

/** One DAG node's live state within a {@link StatusEvent}. */
export interface SseNode {
  status: string;
  attempts: number;
  error: string | null;
}

/** The `status` frame from `GET /packages/{id}/events` (scheduler `_status_event`). */
export interface StatusEvent {
  project_id: string;
  phase: string | null;
  cost_usd: number;
  nodes: Record<string, SseNode>;
  critical_path_s: number;
  final_url: string | null;
  complete: boolean;
}

/** Subscribe to a run's live status stream; `.close()` the returned source on unmount. */
export function openEvents(projectId: string, handlers: SseHandlers<StatusEvent>): EventSource {
  return openSse(`${SCHEDULER_URL}/packages/${projectId}/events`, handlers);
}

/** The `status` frame from `GET /jobs/{jobId}/events`. `stage` is the live chain step;
 *  `project_id` is set only on `succeeded`, `errors` only on `failed`. */
export interface PlanningEvent {
  job_id: string;
  status: "queued" | "running" | "succeeded" | "failed";
  stage: string | null;
  project_id: string | null;
  errors: string[] | null;
}

/** Subscribe to a planning job's progress stream; `.close()` the source on unmount. */
export function openPlanningEvents(
  jobId: string,
  handlers: SseHandlers<PlanningEvent>,
): EventSource {
  return openSse(`${PLANNING_URL}/jobs/${jobId}/events`, handlers);
}
