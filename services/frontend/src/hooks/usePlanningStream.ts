import { useEffect, useRef, useState } from "react";
import { openPlanningEvents, type PlanningEvent } from "@/api/client";

type StreamConnection = "connecting" | "live" | "reconnecting" | "closed";

interface PlanningStream {
  event: PlanningEvent | null;
  /** `Date.now()` when the last frame landed — the base the screen smooths its elapsed
   *  counters against between frames. */
  receivedAt: number;
  connection: StreamConnection;
}

const TERMINAL: ReadonlySet<string> = new Set(["succeeded", "failed"]);

/** Subscribe to a planning job's progress SSE, reporting connection health alongside
 *  the last frame.
 *
 *  Closing the source at a terminal status is load-bearing: the server ends the stream
 *  itself, which fires `error` in the browser and starts a reconnect the screen would
 *  otherwise render as "Reconnecting..." during the success dwell. */
export function usePlanningStream(jobId: string): PlanningStream {
  const [stream, setStream] = useState<PlanningStream>({
    event: null,
    receivedAt: Date.now(),
    connection: "connecting",
  });
  const closed = useRef(false);

  useEffect(() => {
    if (!jobId) return;
    closed.current = false;
    const source = openPlanningEvents(jobId, {
      onStatus: (incoming) => {
        const terminal = TERMINAL.has(incoming.status);
        if (terminal) {
          closed.current = true;
          source.close();
        }
        setStream({
          event: incoming,
          receivedAt: Date.now(),
          connection: terminal ? "closed" : "live",
        });
      },
      onError: () => {
        if (closed.current) return;
        setStream((prev) => ({
          ...prev,
          // No frame yet means the connection never came up; otherwise the browser's
          // native retry is already at work and the last frame stays on screen.
          connection: prev.event ? "reconnecting" : "connecting",
        }));
      },
    });
    return () => {
      closed.current = true;
      source.close();
    };
  }, [jobId]);

  return stream;
}
