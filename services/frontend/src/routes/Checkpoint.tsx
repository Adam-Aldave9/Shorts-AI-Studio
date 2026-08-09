// Checkpoint screen — the human-in-the-loop gate. Queries and the loading/error gate only;
// the editing surface is CheckpointEditor.

import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getPackage, getPackageStatus } from "@/api/client";
import { ErrorBanner, Spinner } from "@/components/ui";
import CheckpointEditor from "@/components/checkpoint/CheckpointEditor";

export default function Checkpoint() {
  const { projectId = "" } = useParams();

  const packageQuery = useQuery({
    queryKey: ["package", projectId],
    queryFn: () => getPackage(projectId),
    enabled: Boolean(projectId),
    // The JSON tab commits structural edits into this cache entry, so a refetch would
    // overwrite local work whenever the cache runs ahead of the server.
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
  const statusQuery = useQuery({
    queryKey: ["packageStatus", projectId],
    queryFn: () => getPackageStatus(projectId),
    enabled: Boolean(projectId),
  });

  const approved = statusQuery.data?.approved === true;
  // Locked while the status is unknown: it resolves independently of the package, so
  // otherwise the UI is briefly editable before `approved: true` lands and the first edit 409s.
  const locked = approved || statusQuery.isPending;

  if (packageQuery.isLoading) return <Spinner label="Loading package..." />;
  if (packageQuery.isError) {
    return <ErrorBanner title="Could not load package" error={packageQuery.error} />;
  }
  const pkg = packageQuery.data;
  if (!pkg) return <ErrorBanner title="Package not found" error={`No package ${projectId}`} />;

  return (
    <div className="mx-auto max-w-7xl">
      <CheckpointEditor
        key={projectId}
        projectId={projectId}
        pkg={pkg}
        locked={locked}
        approved={approved}
      />
    </div>
  );
}
