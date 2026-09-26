// Jump between the versions of one film; each opens on the screen for its phase.

import { useNavigate } from "react-router-dom";
import type { VersionSummary } from "@/api/client";
import { destination } from "@/lib/films";
import { controlClass } from "@/components/ui";

export function VersionSwitcher({
  projectId,
  versions,
}: {
  projectId: string;
  versions: VersionSummary[];
}) {
  const navigate = useNavigate();
  if (versions.length < 2) return null;
  return (
    <select
      className={`${controlClass} w-auto py-1.5`}
      aria-label="Version"
      value={projectId}
      onChange={(event) => {
        const target = versions.find((v) => v.project_id === event.target.value);
        if (target) navigate(destination(target));
      }}
    >
      {versions.map((v) => (
        <option key={v.project_id} value={v.project_id}>
          v{v.version} - {v.title}
          {v.phase === "complete" ? "" : ` (${v.phase ?? "draft"})`}
        </option>
      ))}
    </select>
  );
}
