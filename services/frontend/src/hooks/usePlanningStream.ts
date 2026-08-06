import { useEffect, useState } from "react";
import { openPlanningEvents, type PlanningEvent } from "@/api/client";

/** Subscribe to a planning job's progress SSE. */
export function usePlanningStream(jobId: string): PlanningEvent | null {
  const [event, setEvent] = useState<PlanningEvent | null>(null);
  useEffect(() => {
    if (!jobId) return;
    const source = openPlanningEvents(jobId, { onStatus: setEvent });
    return () => source.close();
  }, [jobId]);
  return event;
}
