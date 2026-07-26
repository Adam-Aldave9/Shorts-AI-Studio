import { useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";

/** A navigate function that fires at most once — guards the terminal-state redirect from
 *  re-firing as further SSE frames arrive. */
export function useNavigateOnce() {
  const navigate = useNavigate();
  const navigated = useRef(false);
  return useCallback(
    (to: string) => {
      if (navigated.current) return;
      navigated.current = true;
      navigate(to);
    },
    [navigate],
  );
}
