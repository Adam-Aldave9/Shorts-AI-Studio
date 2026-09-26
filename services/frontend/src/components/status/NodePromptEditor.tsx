// Inline editor for one failed (or waiting) node of an approved run: edit the prompt or
// narration, optionally ask the AI for a fix, then save (and retry, for a failed node).

import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { patchNode, retryNodes, suggestFix, type Asset, type NodeEdit } from "@/api/client";
import { usePromptLimits } from "@/hooks/usePromptLimits";
import { utf8Bytes } from "@/lib/promptBudget";
import { VOICES } from "@/lib/voices";
import { Button, ErrorBanner, PromptBudget, controlClass } from "@/components/ui";

function currentVoice(asset: Asset): string {
  const raw = asset.spec?.["voice_id"];
  return typeof raw === "string" ? raw : "";
}

export function NodePromptEditor({
  projectId,
  asset,
  retry,
  autoSuggest = false,
  disabledReason,
  onClose,
}: {
  projectId: string;
  asset: Asset;
  /** Failed nodes save and re-render; a waiting node only saves and dispatches on its own. */
  retry: boolean;
  /** Fire "Suggest fix" as soon as the editor opens. */
  autoSuggest?: boolean;
  disabledReason: string | null;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const limitFor = usePromptLimits();
  const isVoiceover = asset.type === "voiceover";
  const stored = (isVoiceover ? asset.text : asset.prompt) ?? "";
  const storedVoice = currentVoice(asset);

  const [draft, setDraft] = useState(stored);
  const [voice, setVoice] = useState(storedVoice);
  const [notes, setNotes] = useState<string | null>(null);

  const limit = isVoiceover ? undefined : limitFor(asset.provider_hint);
  const overLimit = limit !== undefined && utf8Bytes(draft) > limit;
  const blank = !draft.trim();

  const suggest = useMutation({
    mutationFn: () => suggestFix(projectId, asset.node_id, draft),
    onSuccess: (suggestion) => {
      setDraft(suggestion.prompt);
      setNotes(suggestion.notes);
    },
  });

  const suggestOnOpen = useRef(autoSuggest && !isVoiceover);
  useEffect(() => {
    if (!suggestOnOpen.current || disabledReason) return;
    suggestOnOpen.current = false;
    suggest.mutate();
  }, [suggest, disabledReason]);

  const save = useMutation({
    mutationFn: async () => {
      const edit: NodeEdit = isVoiceover ? { text: draft } : { prompt: draft };
      if (isVoiceover && voice && voice !== storedVoice) edit.voice_id = voice;
      await patchNode(projectId, asset.node_id, edit);
      if (retry) await retryNodes(projectId, [asset.node_id]);
    },
    onSuccess: onClose,
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["runPackage", projectId] });
      queryClient.invalidateQueries({ queryKey: ["package", projectId] });
    },
  });

  const busy = suggest.isPending || save.isPending;
  const voices = VOICES.filter((option) => option.id);
  const knownVoice = voices.some((option) => option.id === storedVoice);

  return (
    <div className="mt-3 space-y-2 rounded-md border border-border bg-surface p-3">
      <label
        className="block text-xs uppercase tracking-wide text-fg-subtle"
        htmlFor={`edit-${asset.node_id}`}
      >
        {isVoiceover ? "Narration" : "Prompt"} - {asset.node_id}
      </label>
      <textarea
        id={`edit-${asset.node_id}`}
        className={`${controlClass} min-h-[9rem] leading-relaxed`}
        value={draft}
        disabled={busy || Boolean(disabledReason)}
        onChange={(event) => setDraft(event.target.value)}
      />
      <PromptBudget value={draft} limit={limit} />

      {isVoiceover && (
        <label className="block text-sm">
          <span className="text-xs uppercase tracking-wide text-fg-subtle">Voice</span>
          <select
            className={`${controlClass} mt-1`}
            value={voice}
            disabled={busy || Boolean(disabledReason)}
            onChange={(event) => setVoice(event.target.value)}
          >
            {!knownVoice && <option value={storedVoice}>Current ({storedVoice || "none"})</option>}
            {voices.map((option) => (
              <option key={option.id} value={option.id}>
                {option.name}
              </option>
            ))}
          </select>
        </label>
      )}

      {notes && <p className="text-xs text-fg-muted">Suggestion: {notes}</p>}
      {suggest.isError && <ErrorBanner title="Could not suggest a fix" error={suggest.error} />}
      {save.isError && <ErrorBanner title="Could not save" error={save.error} />}

      <div className="flex flex-wrap items-center justify-end gap-2">
        <Button variant="ghost" onClick={onClose} disabled={save.isPending}>
          Cancel
        </Button>
        {!isVoiceover && (
          <Button
            variant="secondary"
            onClick={() => suggest.mutate()}
            disabled={busy || Boolean(disabledReason)}
          >
            {suggest.isPending ? "Suggesting..." : "Suggest fix"}
          </Button>
        )}
        <Button
          onClick={() => save.mutate()}
          disabled={busy || blank || overLimit || Boolean(disabledReason)}
          title={overLimit ? "Shorten the prompt to fit the byte limit first" : undefined}
        >
          {save.isPending ? "Saving..." : retry ? "Save & retry" : "Save"}
        </Button>
      </div>
    </div>
  );
}
