import { useEffect, useState } from "react";

/** A ticking clock (epoch ms), so elapsed counters advance on their own rather than
 *  riding on whatever cadence SSE frames happen to arrive at. */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);
  return now;
}
