// Plain-language copy and offered actions for each provider failure code. The code drives
// the UI; the provider's own message is shown alongside it, never instead of it.

import type { Asset, ErrorCode } from "@/api/client";

export type FailureAction = "suggest" | "edit" | "retry";

interface FailureDescription {
  title: string;
  remedy: string;
  /** Offered actions, primary first. */
  actions: FailureAction[];
  /** Not fixable by editing one node: failures sharing the code are grouped into one card. */
  systemic: boolean;
}

const COPY: Record<ErrorCode, Omit<FailureDescription, "systemic">> = {
  prompt_too_long: {
    title: "Prompt too long for this model",
    remedy:
      "Shorten it to fit. The limit counts bytes, so dashes, curly quotes and accented letters count extra.",
    actions: ["suggest", "edit"],
  },
  content_policy: {
    title: "Blocked by the provider's content filter",
    remedy:
      "Rephrase to show the moment through tension and motion rather than graphic action (no injuries, blood, or weapons aimed at people). The filter can also react to the start image.",
    actions: ["suggest", "edit", "retry"],
  },
  input_image: {
    title: "The start image couldn't be used",
    remedy:
      "The provider couldn't load this shot's reference image (it may have expired). Try again; if it keeps failing, the reference image needs re-rendering.",
    actions: ["retry"],
  },
  invalid_input: {
    title: "The provider rejected this request",
    remedy: "Check the prompt against the technical details below.",
    actions: ["edit", "suggest", "retry"],
  },
  timeout: {
    title: "The provider took too long",
    remedy:
      "The job didn't finish within 20 minutes. Retrying submits a new job; the earlier one may still be billed.",
    actions: ["retry"],
  },
  auth: {
    title: "Provider credentials rejected",
    remedy: "Not fixable by editing. Check the provider API key, then retry.",
    actions: ["retry"],
  },
  quota: {
    title: "Provider credits exhausted",
    remedy: "Top up the provider account, then retry.",
    actions: ["retry"],
  },
  rate_limited: {
    title: "Provider temporarily unavailable",
    remedy: "Retried automatically; try again in a moment.",
    actions: ["retry"],
  },
  provider_unavailable: {
    title: "Provider temporarily unavailable",
    remedy: "Retried automatically; try again in a moment.",
    actions: ["retry"],
  },
  internal: {
    title: "Render crashed",
    remedy: "An unexpected pipeline error. Retry; if it repeats, check the worker logs.",
    actions: ["retry"],
  },
  unknown: {
    title: "Render failed",
    remedy: "See the technical details.",
    actions: ["edit", "retry"],
  },
};

const SYSTEMIC = new Set<ErrorCode>([
  "auth",
  "quota",
  "rate_limited",
  "provider_unavailable",
  "internal",
]);

export function describeFailure(
  code: ErrorCode | null,
  nodeType: Asset["type"],
): FailureDescription {
  const copy = COPY[code ?? "unknown"] ?? COPY.unknown;
  // Suggest fix rewrites image/video prompts only.
  const actions =
    nodeType === "voiceover" ? copy.actions.filter((action) => action !== "suggest") : copy.actions;
  return { ...copy, actions, systemic: code !== null && SYSTEMIC.has(code) };
}
