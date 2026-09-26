// Its own module so exporting non-components keeps `react-refresh/only-export-components` quiet.

import type { ProposalRequest } from "@/api/client";

export type StudioStep = "brief" | "world" | "script" | "shots" | "review";

export const STUDIO_STEPS: ReadonlyArray<{ id: StudioStep; label: string }> = [
  { id: "brief", label: "Brief" },
  { id: "world", label: "World" },
  { id: "script", label: "Script" },
  { id: "shots", label: "Shots" },
  { id: "review", label: "Review" },
];

/** What the proposal dialog is asked to rewrite. */
export interface ProposalConfig {
  stage: ProposalRequest["stage"];
  targets: string[];
  title: string;
  notes?: string;
}

// Notes prefilled by the Brief tab's contextual rewrite buttons.
export const PREFILLED_NOTES = {
  restyleWorld: (style: string) =>
    `Update every canonical_description for the new visual style "${style}". Keep each entity's identity traits word for word; replace only the closing style sentence.`,
  worldForPremise: (premise: string) =>
    `The premise is now: "${premise}". Rework the cast and set to fit it; keep entities that still fit, word for word.`,
  scriptForPremise: (premise: string) =>
    `The premise is now: "${premise}". Rewrite the screenplay for it, reusing the cast and locations.`,
  retimeScript: (seconds: number) =>
    `Retime the script for a ${seconds}-second film: adjust the number of scenes and the narration length so that, read aloud, it fills ${seconds} seconds.`,
};
