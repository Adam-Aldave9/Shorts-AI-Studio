// Split out of the route so it can take a defined `pkg`: the route's early returns sit after
// every hook, so a hook needing the package cannot live there without typing it
// `ProductionPackage | undefined`.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useBeforeUnload, useBlocker, useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { approvePackage, isConflict, updatePackage, type ProductionPackage } from "@/api/client";
import { usePackageDraft } from "@/hooks/usePackageDraft";
import { videoShots } from "@/lib/package";
import { Button, ErrorBanner, SuccessBanner, Tabs, WarningBanner } from "@/components/ui";
import { CheckpointHeader } from "./CheckpointHeader";
import { StoryPanel } from "./StoryPanel";
import { ShotWorkbench } from "./ShotWorkbench";
import { JsonPanel } from "./JsonPanel";
import type { CheckpointTab } from "./tabs";

export default function CheckpointEditor({
  projectId,
  pkg,
  locked,
  approved,
}: {
  projectId: string;
  pkg: ProductionPackage;
  /** Approved, or the status not yet known. */
  locked: boolean;
  approved: boolean;
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const draftApi = usePackageDraft(projectId, pkg);

  const [tab, setTab] = useState<CheckpointTab>("story");
  const [jsonText, setJsonText] = useState(() => JSON.stringify(pkg, null, 2));
  const [parseError, setParseError] = useState<string | null>(null);
  // Approve navigates on its own once the save has landed; the nav guard must not block it.
  const approvingRef = useRef(false);

  const approveMutation = useMutation({
    mutationFn: () => approvePackage(projectId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["packageStatus", projectId] });
      navigate(`/status/${projectId}`);
    },
    onError: (error) => {
      approvingRef.current = false;
      if (isConflict(error)) {
        queryClient.invalidateQueries({ queryKey: ["packageStatus", projectId] });
      }
    },
  });

  const saveMutation = useMutation({
    mutationFn: (next: ProductionPackage) => updatePackage(projectId, next),
    onSuccess: (saved) => {
      // The identity change re-seeds the draft hook; Monaco's text is not, so rewrite it.
      queryClient.setQueryData(["package", projectId], saved);
      setJsonText(JSON.stringify(saved, null, 2));
    },
    onError: (error) => {
      if (isConflict(error)) {
        queryClient.invalidateQueries({ queryKey: ["packageStatus", projectId] });
      }
    },
  });

  // Read-only during an in-flight PUT so the draft cannot diverge from the snapshot sent.
  const readOnly = locked || saveMutation.isPending;
  const busy = saveMutation.isPending || approveMutation.isPending;

  // Memoized: unmemoized this is a ~25 KB stringify on every Monaco keystroke.
  const savedText = useMemo(() => JSON.stringify(draftApi.saved, null, 2), [draftApi.saved]);
  const jsonDirty = tab === "json" && jsonText !== savedText;
  const dirty = draftApi.dirty || jsonDirty;

  function parseJson(): ProductionPackage | null {
    try {
      const parsed = JSON.parse(jsonText) as ProductionPackage;
      setParseError(null);
      return parsed;
    } catch (error) {
      setParseError(error instanceof Error ? error.message : "Invalid JSON");
      return null;
    }
  }

  /** What Save/Approve would PUT: the visible editor is the authoritative one. */
  function pendingPackage(): ProductionPackage | null {
    return tab === "json" ? parseJson() : draftApi.merged;
  }

  function onSave() {
    if (readOnly || busy) return;
    const pending = pendingPackage();
    if (!pending) return; // broken JSON — banner already shown
    saveMutation.mutate(pending);
  }

  // mutateAsync so a failed save (422/409) blocks approval instead of approving stale work.
  async function onApprove() {
    if (readOnly || busy) return;
    if (dirty) {
      const pending = pendingPackage();
      if (!pending) return;
      try {
        await saveMutation.mutateAsync(pending);
      } catch {
        return;
      }
    }
    approvingRef.current = true;
    approveMutation.mutate();
  }

  function selectTab(next: CheckpointTab) {
    if (next === tab) return;
    if (tab === "json") {
      // Refusing to leave keeps the user's text, which is why the tab strip and the parse
      // banner both render outside the panel.
      const parsed = parseJson();
      if (!parsed) return;
      if (!readOnly) draftApi.commitPackage(parsed);
    } else if (next === "json") {
      setJsonText(JSON.stringify(draftApi.merged, null, 2));
      setParseError(null);
    }
    setTab(next);
  }

  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      dirty &&
      !locked &&
      !approvingRef.current &&
      currentLocation.pathname !== nextLocation.pathname,
  );
  useBeforeUnload(
    useCallback(
      (event: BeforeUnloadEvent) => {
        if (dirty && !locked) event.preventDefault();
      },
      [dirty, locked],
    ),
  );
  // A save while the prompt is open makes the block irrelevant; don't leave it on screen.
  useEffect(() => {
    if (blocker.state === "blocked" && !dirty) blocker.reset?.();
  }, [blocker, dirty]);

  // `onSave` re-checks readOnly/busy itself, so the listener registers once via a ref.
  const saveRef = useRef(onSave);
  saveRef.current = onSave;
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "s" || !(event.ctrlKey || event.metaKey)) return;
      event.preventDefault();
      saveRef.current();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <div>
      <div className="sticky top-[calc(theme(spacing.header)+1px)] z-10 -mx-6 border-b border-border bg-surface/95 px-6 pb-3 backdrop-blur">
        <CheckpointHeader
          pkg={draftApi.merged}
          locked={locked}
          approved={approved}
          dirty={dirty}
          saving={saveMutation.isPending}
          approving={approveMutation.isPending}
          onSave={onSave}
          onApprove={onApprove}
          onRevert={draftApi.resetAll}
          onLeave={() => navigate("/history")}
        />
        <Tabs
          className="mt-3 max-w-md"
          tabs={[
            { id: "story" as const, label: "Story" },
            { id: "shots" as const, label: "Shots", badge: videoShots(pkg).length },
            { id: "json" as const, label: "JSON" },
          ]}
          active={tab}
          onChange={selectTab}
        />
      </div>

      <div className="mt-4 space-y-2 empty:hidden">
        {approved && (
          <WarningBanner>
            Approved and running — view only.{" "}
            <button
              className="underline hover:text-warning/80"
              onClick={() => navigate(`/status/${projectId}`)}
            >
              Open the live status
            </button>
            .
          </WarningBanner>
        )}
        {saveMutation.isError && (
          <ErrorBanner
            title={
              isConflict(saveMutation.error)
                ? "Run already started — package is locked"
                : "Validation failed"
            }
            error={saveMutation.error}
          />
        )}
        {approveMutation.isError && (
          <ErrorBanner
            title={
              isConflict(approveMutation.error)
                ? "Run already started — package is locked"
                : "Could not approve"
            }
            error={approveMutation.error}
          />
        )}
        {saveMutation.isSuccess && !saveMutation.isPending && (
          <SuccessBanner>Saved and re-validated.</SuccessBanner>
        )}
      </div>

      <div className="mt-4">
        {tab === "story" && (
          <StoryPanel
            pkg={pkg}
            draft={draftApi.draft}
            setMeta={draftApi.setMeta}
            setNode={draftApi.setNode}
            readOnly={readOnly}
          />
        )}
        {tab === "shots" && (
          <ShotWorkbench
            pkg={pkg}
            nodeValue={draftApi.nodeValue}
            setNode={draftApi.setNode}
            isNodeDirty={draftApi.isNodeDirty}
            resetNode={draftApi.resetNode}
            readOnly={readOnly}
          />
        )}
        {tab === "json" && (
          <JsonPanel
            value={jsonText}
            readOnly={readOnly}
            parseError={parseError}
            onChange={setJsonText}
            // From `merged`, not the cached package: reseeding from a different document
            // than tab-entry used would discard the form's edits too.
            onDiscard={() => {
              setParseError(null);
              setJsonText(JSON.stringify(draftApi.merged, null, 2));
            }}
          />
        )}
      </div>

      {blocker.state === "blocked" && (
        <div className="fixed inset-0 z-20 flex items-center justify-center bg-surface/80 p-6 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-xl border bg-surface-raised p-6">
            <h2 className="text-lg font-semibold">Discard unsaved changes?</h2>
            <p className="mt-2 text-sm text-fg-muted">
              This package has edits that have not been saved. Leaving now throws them away.
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <Button variant="secondary" onClick={() => blocker.reset?.()}>
                Keep editing
              </Button>
              <Button variant="danger" onClick={() => blocker.proceed?.()}>
                Discard and leave
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
