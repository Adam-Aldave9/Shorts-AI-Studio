import { useQuery } from "@tanstack/react-query";
import { listVersions } from "@/api/client";

/** Every version of the film this package belongs to, oldest first. */
export function useVersions(projectId: string) {
  return useQuery({
    queryKey: ["versions", projectId],
    queryFn: () => listVersions(projectId),
    enabled: Boolean(projectId),
  });
}
