import { useEffect, useState } from "react";
import { previewRevision, type RevisionPreview, type RevisionRequest } from "@/api/client";

const DEBOUNCE_MS = 400;

/** The server's change analysis for the studio's current draft, re-requested (debounced) on
 *  every edit. A newer request aborts the one in flight, and the last good result stays on
 *  screen while the next one loads. */
export function useRevisionPreview(projectId: string, request: RevisionRequest) {
  const [preview, setPreview] = useState<RevisionPreview | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const body = JSON.stringify(request);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    const timer = setTimeout(() => {
      previewRevision(projectId, JSON.parse(body) as RevisionRequest, controller.signal)
        .then((result) => {
          setPreview(result);
          setError(null);
          setLoading(false);
        })
        .catch((caught: unknown) => {
          if (controller.signal.aborted) return;
          setError(caught);
          setLoading(false);
        });
    }, DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [projectId, body]);

  return { preview, error, loading };
}
