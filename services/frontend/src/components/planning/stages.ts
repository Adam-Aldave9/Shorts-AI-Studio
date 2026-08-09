// The planning chain's stages as the user sees them. `key` must match the backend's
// `PLAN_STAGES` (libs/state) — each frame's `stage` is one of these.

import type { PlanningStageDetail } from "@/api/client";

export interface StageSpec {
  key: string;
  label: string;
  /** One sentence, shown while the stage is active. */
  explainer: string;
  /** Rough seconds on a real run. Doubles as the aggregate bar's weight, so there is no
   *  second table to drift. Guesses until a live run's `stage ... finished in` log lines
   *  replace them with measurements. */
  typicalS: number;
}

export const STAGES: StageSpec[] = [
  {
    key: "world",
    label: "Building the world",
    explainer:
      "Inventing the cast and locations, each with a canonical description every later stage reuses.",
    typicalS: 25,
  },
  {
    key: "script",
    label: "Writing the script",
    explainer: "Turning the premise into scenes with beats and narration.",
    typicalS: 45,
  },
  {
    key: "breakdown",
    label: "Breaking down shots",
    explainer: "Splitting each scene into 3-5 second shots tagged with subjects and location.",
    typicalS: 30,
  },
  {
    key: "prompts",
    label: "Writing shot prompts",
    explainer:
      "Weaving the canonical descriptions into one image-to-video prompt per shot - this is what keeps subjects consistent.",
    typicalS: 90,
  },
  {
    key: "assemble",
    label: "Assembling the package",
    explainer: "Building the render DAG, timeline, and cost estimate, then validating.",
    typicalS: 2,
  },
];

function nameList(names: string[], limit = 3): string {
  const shown = names.slice(0, limit).join(", ");
  return names.length > limit ? `${shown}, +${names.length - limit} more` : shown;
}

/** One line naming what a stage produced, or `null` when it hasn't said yet. */
export function renderDetail(
  stage: string,
  detail: PlanningStageDetail | undefined,
): string | null {
  if (!detail) return null;
  switch (stage) {
    case "world": {
      const characters = detail.characters ?? [];
      const locations = detail.locations ?? [];
      if (!characters.length && !locations.length) return null;
      return `${characters.length} characters, ${locations.length} locations: ${nameList([...characters, ...locations], 4)}`;
    }
    case "script": {
      if (!detail.title) return null;
      return detail.scenes ? `"${detail.title}" - ${detail.scenes} scenes` : `"${detail.title}"`;
    }
    case "breakdown":
      return detail.shots ? `${detail.shots} shots` : null;
    case "prompts":
      return detail.total ? `${detail.done ?? 0} / ${detail.total} prompts written` : null;
    case "assemble": {
      if (!detail.nodes) return null;
      const cost = detail.cost_estimate_usd;
      const nodes = `${detail.nodes} nodes, ${detail.shots ?? 0} shots`;
      return cost === undefined ? nodes : `${nodes}, ~$${cost.toFixed(2)} estimated`;
    }
    default:
      return null;
  }
}

/** The fraction of a stage that is done, or `null` when only the stage itself knows. */
export function detailFraction(detail: PlanningStageDetail | undefined): number | null {
  if (!detail?.total) return null;
  return Math.min(1, (detail.done ?? 0) / detail.total);
}
