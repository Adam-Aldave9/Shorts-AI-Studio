// The single edit draft the Story, Shots and JSON panels all write to.
//
// Three layers, because dirtiness cannot be measured against the query cache alone:
//
//   saved  the last package the *server* acknowledged (initial fetch, save success)
//   base   `saved` plus structural edits committed from the JSON tab. This *is* the cache.
//   draft  field-level edits on top of `base`
//
// Collapsing `saved` into the cache makes a Form -> JSON -> Form round-trip clear `dirty`,
// and Approve then skips the save and approves the server's stale copy silently.

import { useCallback, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { ProductionPackage } from "@/api/client";
import {
  draftEquals,
  draftFromPackage,
  mergeDraft,
  type DraftMetaKey,
  type PackageDraft,
} from "@/lib/packageDraft";

export interface PackageDraftApi {
  draft: PackageDraft;
  /** `base` + `draft` — what Save PUTs and what the JSON tab serializes. */
  merged: ProductionPackage;
  saved: ProductionPackage;
  dirty: boolean;
  setMeta: (key: DraftMetaKey, value: string) => void;
  setNode: (nodeId: string, value: string) => void;
  nodeValue: (nodeId: string) => string;
  isNodeDirty: (nodeId: string) => boolean;
  resetNode: (nodeId: string) => void;
  resetAll: () => void;
  /** Commit a package parsed from the JSON tab into `base`. Does *not* move `saved` — the
   *  server has not seen it, so the result is still unsaved work. */
  commitPackage: (next: ProductionPackage) => void;
}

interface DraftState {
  base: ProductionPackage;
  saved: ProductionPackage;
  savedDraft: PackageDraft;
  /** The reset target for nodes a JSON commit added that the server has never seen. */
  baseDraft: PackageDraft;
  draft: PackageDraft;
}

function seed(pkg: ProductionPackage): DraftState {
  const draft = draftFromPackage(pkg);
  return { base: pkg, saved: pkg, savedDraft: draft, baseDraft: draft, draft };
}

function baselineValue(state: DraftState, nodeId: string): string | undefined {
  if (nodeId in state.savedDraft.nodes) return state.savedDraft.nodes[nodeId];
  return state.baseDraft.nodes[nodeId];
}

export function usePackageDraft(projectId: string, pkg: ProductionPackage): PackageDraftApi {
  const queryClient = useQueryClient();
  const [state, setState] = useState<DraftState>(() => seed(pkg));

  // Re-seed during render rather than in an effect: an effect would commit one frame still
  // showing the pre-save draft. `current` is used below so this pass stays consistent.
  let current = state;
  if (current.base !== pkg) {
    current = seed(pkg);
    setState(current);
  }

  const { base, saved, savedDraft, draft } = current;

  const merged = useMemo(() => mergeDraft(base, draft), [base, draft]);
  const dirty = base !== saved || !draftEquals(draft, savedDraft);

  // Functional updaters with `[]` deps: closing over `draft` would give each setter a fresh
  // identity per keystroke and defeat the memoized rail rows.
  const setMeta = useCallback((key: DraftMetaKey, value: string) => {
    setState((prev) => ({
      ...prev,
      draft: { ...prev.draft, meta: { ...prev.draft.meta, [key]: value } },
    }));
  }, []);

  const setNode = useCallback((nodeId: string, value: string) => {
    setState((prev) => ({
      ...prev,
      draft: { ...prev.draft, nodes: { ...prev.draft.nodes, [nodeId]: value } },
    }));
  }, []);

  const resetNode = useCallback((nodeId: string) => {
    setState((prev) => {
      const baseline = baselineValue(prev, nodeId);
      if (baseline === undefined || prev.draft.nodes[nodeId] === baseline) return prev;
      return {
        ...prev,
        draft: { ...prev.draft, nodes: { ...prev.draft.nodes, [nodeId]: baseline } },
      };
    });
  }, []);

  const resetAll = useCallback(() => {
    // `base` re-seeds off the cache, so a full revert has to restore the cache too. Outside
    // the updater because React may invoke an updater twice.
    queryClient.setQueryData(["package", projectId], saved);
    setState((prev) => ({
      base: prev.saved,
      saved: prev.saved,
      savedDraft: prev.savedDraft,
      baseDraft: prev.savedDraft,
      draft: prev.savedDraft,
    }));
  }, [queryClient, projectId, saved]);

  const commitPackage = useCallback(
    (next: ProductionPackage) => {
      // Read the reference back: TanStack's structural sharing (`replaceEqualDeep`) means the
      // cache may not hold the object passed in. Setting `base` from what the cache actually
      // holds keeps the render-phase re-seed from firing on our own write — no "was this
      // write mine?" flag needed, since every other identity change still re-seeds.
      const stored = queryClient.setQueryData<ProductionPackage>(["package", projectId], next);
      const committed = stored ?? next;
      const committedDraft = draftFromPackage(committed);
      setState((prev) => ({
        ...prev,
        base: committed,
        baseDraft: committedDraft,
        // Re-seeded so prompt edits made in the JSON tab reach the form fields too.
        draft: committedDraft,
      }));
    },
    [queryClient, projectId],
  );

  // Unstable by nature — both close over `draft`. Callers must pass plain values down to
  // memoized children, never these functions.
  const nodeValue = (nodeId: string) => draft.nodes[nodeId] ?? "";
  const isNodeDirty = (nodeId: string) => {
    const baseline = baselineValue(current, nodeId);
    return baseline !== undefined && draft.nodes[nodeId] !== baseline;
  };

  return {
    draft,
    merged,
    saved,
    dirty,
    setMeta,
    setNode,
    nodeValue,
    isNodeDirty,
    resetNode,
    resetAll,
    commitPackage,
  };
}
