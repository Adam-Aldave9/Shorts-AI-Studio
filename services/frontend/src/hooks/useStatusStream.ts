import { useEffect, useState } from "react";
import { openEvents, type StatusEvent } from "@/api/client";

/** Subscribe to a run's live status SSE. Pass `closeOnComplete` on the Result screen so a
 *  finished run's stream isn't reopened in a reconnect loop. */
export function useStatusStream(projectId: string, closeOnComplete = false): StatusEvent | null {
  const [event, setEvent] = useState<StatusEvent | null>(null);
  useEffect(() => {
    if (!projectId) return;
    const source = openEvents(projectId, {
      onStatus: (incoming) => {
        setEvent(incoming);
        if (closeOnComplete && incoming.complete) source.close();
      },
    });
    return () => source.close();
  }, [projectId, closeOnComplete]);
  return event;
}
