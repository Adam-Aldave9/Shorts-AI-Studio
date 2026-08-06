// Normalize any thrown value into human-readable lines. The scheduler's 422 carries the
// validator's error list in `detail`, so the checkpoint renders each failing rule inline.

import { ApiError } from "@/api/client";

export function errorToMessages(error: unknown): string[] {
  if (error instanceof ApiError) {
    const { detail } = error;
    if (Array.isArray(detail)) {
      // Two shapes land here: the scheduler's semantic validator (plain strings) and
      // FastAPI's request validation (a list of {loc, msg} objects).
      return detail.map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object" && "msg" in item) {
          const entry = item as { loc?: unknown[]; msg?: string };
          const location = Array.isArray(entry.loc) ? entry.loc.join(".") : "";
          return location ? `${location}: ${entry.msg}` : String(entry.msg);
        }
        return JSON.stringify(item);
      });
    }
    if (typeof detail === "string") return [detail];
    if (detail && typeof detail === "object") return [JSON.stringify(detail)];
    return [`Request failed (HTTP ${error.status})`];
  }
  if (error instanceof Error) return [error.message];
  return [String(error)];
}
