import { useQuery } from "@tanstack/react-query";
import { getReusePlan } from "@/api/client";

/** Which nodes of a revision reuse an earlier version's render. Only revisions have
 *  anything to reuse, so v1 makes no call. */
export function useReusePlan(projectId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["reuse", projectId],
    queryFn: () => getReusePlan(projectId),
    enabled: enabled && Boolean(projectId),
  });
}
