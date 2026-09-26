// Revision Studio route. Queries and the loading/error gate only; the editor is
// RevisionStudio.

import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getStory } from "@/api/client";
import { ErrorBanner, Spinner } from "@/components/ui";
import RevisionStudio from "@/components/revise/RevisionStudio";

export default function Revise() {
  const { projectId = "" } = useParams();
  const storyQuery = useQuery({
    queryKey: ["story", projectId],
    queryFn: () => getStory(projectId),
    enabled: Boolean(projectId),
    // The studio seeds its draft from this once; a background refetch mustn't reset it.
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });

  if (storyQuery.isLoading) return <Spinner label="Loading the story..." />;
  if (storyQuery.isError) {
    return <ErrorBanner title="Could not load this version's story" error={storyQuery.error} />;
  }
  const view = storyQuery.data;
  if (!view) return <ErrorBanner title="Story not found" error={`No package ${projectId}`} />;

  return (
    <div className="mx-auto max-w-7xl">
      <RevisionStudio key={`${projectId}:${view.base_hash}`} projectId={projectId} view={view} />
    </div>
  );
}
