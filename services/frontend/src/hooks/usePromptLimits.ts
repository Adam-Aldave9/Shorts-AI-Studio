import { useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { getLimits } from "@/api/client";

/** The byte limit for a provider hint's prompt, or `undefined` when none is known. */
export function usePromptLimits(): (hint: string | null | undefined) => number | undefined {
  const { data } = useQuery({ queryKey: ["limits"], queryFn: getLimits, staleTime: Infinity });
  return useCallback((hint) => (hint ? data?.prompt_max_bytes[hint] : undefined), [data]);
}
