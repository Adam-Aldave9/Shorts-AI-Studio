/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_PLANNING_URL: string;
  readonly VITE_SCHEDULER_URL: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
