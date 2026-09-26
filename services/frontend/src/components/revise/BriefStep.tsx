// The Brief tab: premise, length, style and voice, each with a note on what changing it
// regenerates and, where it helps, a one-click AI rewrite of the stages it affects.

import type { ReactNode } from "react";
import { DURATIONS, STYLES } from "@/lib/briefOptions";
import type { StoryAction, StoryDraft } from "@/lib/story";
import { VOICES } from "@/lib/voices";
import { Button, Card, Field, cn, controlClass } from "@/components/ui";
import { PREFILLED_NOTES, type ProposalConfig } from "./steps";

const MAX_PREMISE = 500;

function Impact({ children }: { children: ReactNode }) {
  return (
    <div className="mt-2 flex flex-wrap items-center gap-2 rounded-md border border-accent/30 bg-accent/10 px-3 py-2 text-xs text-fg-muted">
      {children}
    </div>
  );
}

function AiButton({ onClick, children }: { onClick: () => void; children: ReactNode }) {
  return (
    <Button variant="secondary" className="px-2 py-1 text-xs" onClick={onClick}>
      {children}
    </Button>
  );
}

export function BriefStep({
  draft,
  base,
  dispatch,
  onPropose,
}: {
  draft: StoryDraft;
  base: StoryDraft;
  dispatch: (action: StoryAction) => void;
  onPropose: (config: ProposalConfig) => void;
}) {
  const brief = draft.brief;
  const durations = DURATIONS.includes(brief.target_duration_s)
    ? DURATIONS
    : [...DURATIONS, brief.target_duration_s].sort((a, b) => a - b);
  const voice = brief.narration_voice_id ?? "";
  const knownVoice = VOICES.some((v) => v.id === voice);
  const style = brief.style ?? "";

  return (
    <Card className="space-y-6">
      <Field label="Premise">
        <textarea
          className={controlClass}
          rows={4}
          maxLength={MAX_PREMISE}
          value={brief.premise}
          onChange={(event) =>
            dispatch({ type: "setBrief", field: "premise", value: event.target.value })
          }
        />
        <div className="mt-1 text-right text-xs text-fg-subtle">
          {brief.premise.length}/{MAX_PREMISE}
        </div>
        {brief.premise !== base.brief.premise && (
          <Impact>
            <span>The world and script were written for the old premise.</span>
            <AiButton
              onClick={() =>
                onPropose({
                  stage: "world",
                  targets: [],
                  title: "Rewrite the world for the new premise",
                  notes: PREFILLED_NOTES.worldForPremise(brief.premise),
                })
              }
            >
              Rewrite world with AI
            </AiButton>
            <AiButton
              onClick={() =>
                onPropose({
                  stage: "script",
                  targets: [],
                  title: "Rewrite the script for the new premise",
                  notes: PREFILLED_NOTES.scriptForPremise(brief.premise),
                })
              }
            >
              Rewrite script with AI
            </AiButton>
          </Impact>
        )}
      </Field>

      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
        <Field label="Length">
          <select
            className={controlClass}
            value={brief.target_duration_s}
            onChange={(event) =>
              dispatch({
                type: "setBrief",
                field: "target_duration_s",
                value: Number(event.target.value),
              })
            }
          >
            {durations.map((seconds) => (
              <option key={seconds} value={seconds}>
                {seconds}s
              </option>
            ))}
          </select>
          {brief.target_duration_s !== base.brief.target_duration_s && (
            <Impact>
              <span>Shots will be re-planned to fit {brief.target_duration_s}s.</span>
              <AiButton
                onClick={() =>
                  onPropose({
                    stage: "script",
                    targets: [],
                    title: "Retime the script",
                    notes: PREFILLED_NOTES.retimeScript(brief.target_duration_s),
                  })
                }
              >
                Retime script with AI
              </AiButton>
            </Impact>
          )}
        </Field>

        <Field label="Narration voice">
          <select
            className={controlClass}
            value={voice}
            onChange={(event) =>
              dispatch({
                type: "setBrief",
                field: "narration_voice_id",
                value: event.target.value || null,
              })
            }
          >
            {!knownVoice && <option value={voice}>Current ({voice})</option>}
            {VOICES.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name}
              </option>
            ))}
          </select>
          {brief.narration_voice_id !== base.brief.narration_voice_id && (
            <Impact>Only the narration is re-recorded.</Impact>
          )}
        </Field>
      </div>

      <Field label="Visual style">
        <input
          className={controlClass}
          value={style}
          onChange={(event) =>
            dispatch({ type: "setBrief", field: "style", value: event.target.value })
          }
        />
        <div className="mt-2 flex flex-wrap gap-1.5">
          {STYLES.map((preset) => (
            <button
              key={preset}
              type="button"
              className={cn(
                "rounded-full border px-2.5 py-0.5 text-xs transition",
                preset === style
                  ? "border-accent bg-accent/15 text-fg"
                  : "border-border text-fg-muted hover:border-border-strong hover:text-fg",
              )}
              onClick={() => dispatch({ type: "setBrief", field: "style", value: preset })}
            >
              {preset}
            </button>
          ))}
        </div>
        {style !== (base.brief.style ?? "") && (
          <Impact>
            <span>All shot prompts and reference images will be regenerated.</span>
            <AiButton
              onClick={() =>
                onPropose({
                  stage: "world",
                  targets: [],
                  title: "Restyle the world",
                  notes: PREFILLED_NOTES.restyleWorld(style),
                })
              }
            >
              Restyle world with AI
            </AiButton>
          </Impact>
        )}
      </Field>
    </Card>
  );
}
