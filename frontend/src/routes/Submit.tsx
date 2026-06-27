// Submit screen (spec §9.2): premise + duration + style + voice -> POST /briefs.
// On 201 the planning tier has persisted a package; route to its checkpoint.

import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { submitBrief, type Brief } from "@/api/client";
import { Button, Card, ErrorBanner, Field, controlClass } from "@/components/ui";

// A small curated voice list (ElevenLabs default voice ids). The mock ignores the
// pick; a real run threads it into the voiceover node.
const VOICES = [
  { id: "", name: "Default narrator" },
  { id: "21m00Tcm4TlvDq8ikWAM", name: "Rachel (warm, female)" },
  { id: "pNInz6obpgDQGcFmaJgB", name: "Adam (deep, male)" },
  { id: "ErXwobaYiN019PkySvjV", name: "Antoni (calm, male)" },
  { id: "EXAVITQu4vr4xnSDxMaL", name: "Bella (soft, female)" },
];
const STYLES = ["cinematic", "documentary", "animated", "noir", "nature", "dreamlike"];
const DURATIONS = [30, 60, 90, 120];

export default function Submit() {
  const navigate = useNavigate();
  const [premise, setPremise] = useState("");
  const [duration, setDuration] = useState(90);
  const [style, setStyle] = useState("");
  const [voiceId, setVoiceId] = useState("");

  const mutation = useMutation({
    mutationFn: (brief: Brief) => submitBrief(brief),
    onSuccess: (accepted) => navigate(`/checkpoint/${accepted.project_id}`),
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!premise.trim()) return;
    mutation.mutate({
      premise: premise.trim(),
      target_duration_s: duration,
      style: style || null,
      narration_voice_id: voiceId || null,
    });
  }

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="text-2xl font-semibold">Submit a brief</h1>
      <p className="mt-1 text-sm text-neutral-500">
        Describe the film. Planning compiles it into a production package you review at the
        checkpoint before anything renders.
      </p>

      <Card className="mt-6">
        <form className="space-y-5" onSubmit={onSubmit}>
          <Field label="Premise">
            <textarea
              className={controlClass}
              rows={5}
              value={premise}
              onChange={(event) => setPremise(event.target.value)}
              placeholder="A lone explorer treks through the Amazon rainforest at dawn..."
            />
          </Field>

          <div className="grid grid-cols-1 gap-5 sm:grid-cols-3">
            <Field label="Duration">
              <select
                className={controlClass}
                value={duration}
                onChange={(event) => setDuration(Number(event.target.value))}
              >
                {DURATIONS.map((seconds) => (
                  <option key={seconds} value={seconds}>
                    {seconds}s
                  </option>
                ))}
              </select>
            </Field>

            <Field label="Style">
              <select
                className={controlClass}
                value={style}
                onChange={(event) => setStyle(event.target.value)}
              >
                <option value="">Auto</option>
                {STYLES.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </Field>

            <Field label="Voice">
              <select
                className={controlClass}
                value={voiceId}
                onChange={(event) => setVoiceId(event.target.value)}
              >
                {VOICES.map((voice) => (
                  <option key={voice.id} value={voice.id}>
                    {voice.name}
                  </option>
                ))}
              </select>
            </Field>
          </div>

          {mutation.isError && <ErrorBanner title="Could not submit brief" error={mutation.error} />}

          <div className="flex items-center gap-3">
            <Button type="submit" disabled={!premise.trim() || mutation.isPending}>
              {mutation.isPending ? "Planning..." : "Generate package"}
            </Button>
            <span className="text-xs text-neutral-400">
              Runs the planning chain (mock returns a 30-shot rainforest package).
            </span>
          </div>
        </form>
      </Card>
    </div>
  );
}
