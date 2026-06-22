// Thin fetch wrappers around the planning + scheduler services.
// TODO: replace hand-written calls with the openapi-typescript-generated
// client (`npm run gen:api`). Stub only.

export const PLANNING_URL = import.meta.env.VITE_PLANNING_URL ?? "http://localhost:8000";
export const SCHEDULER_URL = import.meta.env.VITE_SCHEDULER_URL ?? "http://localhost:8001";
