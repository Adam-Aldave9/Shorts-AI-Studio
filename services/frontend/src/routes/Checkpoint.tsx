// Checkpoint screen (spec §4.3, §9.2) - the human-in-the-loop gate that cannot be
// cut. Left pane: a rendered summary of the package the scheduler is serving. Right
// pane: two views of the same package -
//   Form           - structured editing of the safe fields (default).
//   Advanced (JSON) - the raw package in Monaco, schema-validated against GET /schema.
//
//   Approve -> (auto-save any unsaved edits) POST /approve, then route to Status.
//   Save    -> PUT /packages/{id}; the server re-runs the validator and returns 422
//              with the failing rules, shown inline.
//   Reject  -> discard (leave it unapproved) and go back to History.
//
// Once the run has started the package is locked (approved-set membership, surfaced by
// GET /packages/{id}/status): every control goes read-only and Save/Approve disappear.
// A direct edit/re-approve of a locked package 409s; we treat that as "run started".

import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Editor, { useMonaco } from "@monaco-editor/react";
import {
  ApiError,
  approvePackage,
  getPackage,
  getPackageSchema,
  getPackageStatus,
  updatePackage,
  type ProductionPackage,
} from "@/api/client";
import { estimatedTotalUsd, shotDurationS, videoShots, voiceovers } from "@/lib/package";
import { formatDuration, formatUsd } from "@/lib/format";
import { Button, Card, ErrorBanner, Spinner, Stat, SuccessBanner, cn } from "@/components/ui";
import PackageEditForm from "@/components/PackageEditForm";

// Monaco's JSON `jsonDefaults` is not surfaced by the loader's slim types (the
// monaco-editor package types aren't resolved), so narrow to just what we call.
interface JsonLanguageDefaults {
  setDiagnosticsOptions(options: {
    validate?: boolean;
    schemas?: Array<{ uri: string; fileMatch?: string[]; schema?: unknown }>;
  }): void;
}

export default function Checkpoint() {
  const { projectId = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const monaco = useMonaco();

  const packageQuery = useQuery({
    queryKey: ["package", projectId],
    queryFn: () => getPackage(projectId),
    enabled: Boolean(projectId),
  });
  const schemaQuery = useQuery({ queryKey: ["schema"], queryFn: getPackageSchema });
  const statusQuery = useQuery({
    queryKey: ["packageStatus", projectId],
    queryFn: () => getPackageStatus(projectId),
    enabled: Boolean(projectId),
  });
  const locked = statusQuery.data?.approved === true;

  const [advanced, setAdvanced] = useState(false);
  const [draft, setDraft] = useState(""); // Monaco (advanced) draft
  const [parseError, setParseError] = useState<string | null>(null);
  const initializedFor = useRef<string | null>(null);

  // The form's current merged package + dirtiness, kept in a ref so keystrokes don't
  // re-render Checkpoint. Source of truth stays the cached package; this is a live view.
  const formStateRef = useRef<{ merged: ProductionPackage; dirty: boolean }>({
    merged: packageQuery.data ?? ({} as ProductionPackage),
    dirty: false,
  });
  const onFormDraftChange = useCallback((merged: ProductionPackage, dirty: boolean) => {
    formStateRef.current = { merged, dirty };
  }, []);

  // Seed the Monaco editor once per project, then leave it under user control. The
  // save mutation re-seeds it from the server's canonical copy on success.
  useEffect(() => {
    if (packageQuery.data && initializedFor.current !== projectId) {
      setDraft(JSON.stringify(packageQuery.data, null, 2));
      initializedFor.current = projectId;
    }
  }, [packageQuery.data, projectId]);

  // Wire the served JSON schema into Monaco so edits get live validation feedback.
  useEffect(() => {
    if (!monaco || !schemaQuery.data) return;
    const json = (monaco.languages as unknown as { json?: { jsonDefaults: JsonLanguageDefaults } })
      .json;
    json?.jsonDefaults.setDiagnosticsOptions({
      validate: true,
      schemas: [{ uri: "afp://package.schema.json", fileMatch: ["*"], schema: schemaQuery.data }],
    });
  }, [monaco, schemaQuery.data]);

  const approveMutation = useMutation({
    mutationFn: () => approvePackage(projectId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["packageStatus", projectId] });
      navigate(`/status/${projectId}`);
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) {
        queryClient.invalidateQueries({ queryKey: ["packageStatus", projectId] });
      }
    },
  });

  const saveMutation = useMutation({
    mutationFn: (pkg: ProductionPackage) => updatePackage(projectId, pkg),
    onSuccess: (saved) => {
      // Re-seed both views from the server's canonical copy (identity change re-seeds
      // the form; we rewrite the Monaco draft explicitly).
      queryClient.setQueryData(["package", projectId], saved);
      setDraft(JSON.stringify(saved, null, 2));
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) {
        queryClient.invalidateQueries({ queryKey: ["packageStatus", projectId] });
      }
    },
  });

  if (packageQuery.isLoading) return <Spinner label="Loading package..." />;
  if (packageQuery.isError) {
    return <ErrorBanner title="Could not load package" error={packageQuery.error} />;
  }
  const pkg = packageQuery.data;
  if (!pkg) return <ErrorBanner title="Package not found" error={`No package ${projectId}`} />;

  const shots = videoShots(pkg);
  const narration = voiceovers(pkg)[0]?.text ?? null;
  const busy = approveMutation.isPending || saveMutation.isPending;

  /** Parse the Monaco draft into a package, surfacing parse errors in the banner. */
  function parseMonaco(): ProductionPackage | null {
    setParseError(null);
    try {
      return JSON.parse(draft) as ProductionPackage;
    } catch (error) {
      setParseError(error instanceof Error ? error.message : "Invalid JSON");
      return null;
    }
  }

  function onSave() {
    if (locked) return;
    if (advanced) {
      const parsed = parseMonaco();
      if (parsed) saveMutation.mutate(parsed);
    } else {
      saveMutation.mutate(formStateRef.current.merged);
    }
  }

  // Approve, saving any pending edits first — a 422 there blocks approval with the
  // validator banner explaining why. Uses mutateAsync so approve only runs on save ok.
  async function onApprove() {
    if (locked) return;
    const dirty = advanced ? draft !== JSON.stringify(pkg, null, 2) : formStateRef.current.dirty;
    if (dirty) {
      const pending = advanced ? parseMonaco() : formStateRef.current.merged;
      if (!pending) return; // broken JSON — banner already shown
      try {
        await saveMutation.mutateAsync(pending);
      } catch {
        return; // 422/409 surfaced by saveMutation.isError
      }
    }
    approveMutation.mutate();
  }

  // Toggle the right-pane view. Switching carries pending edits across so neither view
  // silently drops them; the visible editor is always the authoritative one.
  function switchToAdvanced() {
    // Form -> Advanced: serialize the form's pending edits into the Monaco draft.
    setDraft(JSON.stringify(formStateRef.current.merged, null, 2));
    setAdvanced(true);
  }
  function switchToForm() {
    // Advanced -> Form: the form re-seeds from the cached package, so the Monaco edits
    // must be committed there first. Block the switch on invalid JSON.
    const parsed = parseMonaco();
    if (!parsed) return;
    queryClient.setQueryData(["package", projectId], parsed);
    setAdvanced(false);
  }
  function discardJsonEdits() {
    setParseError(null);
    setDraft(JSON.stringify(pkg, null, 2));
  }

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">{pkg.meta.title}</h1>
          <p className="font-mono text-xs text-fg-subtle">{pkg.project_id}</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="danger" onClick={() => navigate("/history")} disabled={busy}>
            {locked ? "Back" : "Reject"}
          </Button>
          {!locked && (
            <>
              <Button variant="secondary" onClick={onSave} disabled={busy}>
                {saveMutation.isPending ? "Saving..." : "Save changes"}
              </Button>
              <Button onClick={onApprove} disabled={busy}>
                {approveMutation.isPending ? "Approving..." : "Approve & run"}
              </Button>
            </>
          )}
        </div>
      </div>

      {locked && (
        <div className="mt-4 rounded-md border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-300">
          Approved and running — view only.{" "}
          <button
            className="underline hover:text-amber-200"
            onClick={() => navigate(`/status/${projectId}`)}
          >
            Open the live status
          </button>
          .
        </div>
      )}

      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Left: rendered summary */}
        <div className="space-y-4">
          <div className="grid grid-cols-3 gap-3">
            <Stat label="Shots" value={shots.length} />
            <Stat label="Est. cost" value={formatUsd(estimatedTotalUsd(pkg))} />
            <Stat label="Budget" value={formatUsd(pkg.meta.budget_usd)} />
          </div>

          <Card>
            <dl className="grid grid-cols-3 gap-y-2 text-sm">
              <dt className="text-fg-subtle">Duration</dt>
              <dd className="col-span-2">{formatDuration(pkg.meta.target_duration_s)}</dd>
              <dt className="text-fg-subtle">Style</dt>
              <dd className="col-span-2">{pkg.meta.style}</dd>
              <dt className="text-fg-subtle">Aspect</dt>
              <dd className="col-span-2">{pkg.meta.aspect_ratio}</dd>
              <dt className="text-fg-subtle">Premise</dt>
              <dd className="col-span-2 text-fg-muted">{pkg.meta.premise}</dd>
            </dl>
          </Card>

          {narration && (
            <Card>
              <div className="text-xs uppercase tracking-wide text-fg-subtle">Narration</div>
              <p className="mt-2 whitespace-pre-wrap text-sm text-fg-muted">{narration}</p>
            </Card>
          )}

          <div className="overflow-hidden rounded-xl border bg-surface-raised">
            <div className="bg-surface-overlay px-4 py-2 text-xs uppercase tracking-wide text-fg-subtle">
              Shot list
            </div>
            <div className="max-h-80 overflow-auto">
              <table className="w-full text-left text-sm">
                <thead className="sticky top-0 bg-surface-overlay text-xs uppercase tracking-wide text-fg-subtle">
                  <tr>
                    <th className="px-4 py-2 font-medium">Node</th>
                    <th className="px-4 py-2 font-medium">Prompt</th>
                    <th className="px-4 py-2 text-right font-medium">Dur</th>
                    <th className="px-4 py-2 text-right font-medium">Est.</th>
                  </tr>
                </thead>
                <tbody>
                  {shots.map((shot) => (
                    <tr key={shot.node_id} className="border-t align-top">
                      <td className="px-4 py-2 font-mono text-xs text-fg-subtle">{shot.node_id}</td>
                      <td className="px-4 py-2 text-fg-muted">
                        <div className="line-clamp-2">{shot.prompt ?? "-"}</div>
                        {shot.provider_hint && (
                          <div className="font-mono text-[10px] text-fg-subtle">
                            {shot.provider_hint}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums">
                        {formatDuration(shotDurationS(shot))}
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums">
                        {formatUsd(shot.estimated_cost_usd ?? 0)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* Right: editable views (Form default, Advanced JSON escape hatch) */}
        <div className="space-y-3">
          <div className="flex items-center gap-1 rounded-md border border-border bg-surface-raised p-1 text-sm">
            <button
              className={cn(
                "flex-1 rounded px-3 py-1.5 font-medium transition",
                !advanced ? "bg-surface-overlay text-fg" : "text-fg-muted hover:text-fg",
              )}
              onClick={() => !advanced || switchToForm()}
            >
              Form
            </button>
            <button
              className={cn(
                "flex-1 rounded px-3 py-1.5 font-medium transition",
                advanced ? "bg-surface-overlay text-fg" : "text-fg-muted hover:text-fg",
              )}
              onClick={() => advanced || switchToAdvanced()}
            >
              Advanced (JSON)
            </button>
          </div>

          {parseError && (
            <div className="space-y-2">
              <ErrorBanner title="Invalid JSON" error={parseError} />
              <Button variant="ghost" onClick={discardJsonEdits}>
                Discard JSON edits
              </Button>
            </div>
          )}
          {saveMutation.isError && (
            <ErrorBanner
              title={
                saveMutation.error instanceof ApiError && saveMutation.error.status === 409
                  ? "Run already started — package is locked"
                  : "Validation failed"
              }
              error={saveMutation.error}
            />
          )}
          {approveMutation.isError && (
            <ErrorBanner
              title={
                approveMutation.error instanceof ApiError && approveMutation.error.status === 409
                  ? "Run already started — package is locked"
                  : "Could not approve"
              }
              error={approveMutation.error}
            />
          )}
          {saveMutation.isSuccess && !saveMutation.isPending && (
            <SuccessBanner>Saved and re-validated.</SuccessBanner>
          )}

          {advanced ? (
            <div className="overflow-hidden rounded-xl border">
              <Editor
                height="70vh"
                defaultLanguage="json"
                theme="vs-dark"
                value={draft}
                onChange={(value) => setDraft(value ?? "")}
                options={{
                  minimap: { enabled: false },
                  fontSize: 12,
                  scrollBeyondLastLine: false,
                  tabSize: 2,
                  readOnly: locked,
                }}
              />
            </div>
          ) : (
            <PackageEditForm
              pkg={pkg}
              disabled={locked}
              saving={saveMutation.isPending}
              onDraftChange={onFormDraftChange}
            />
          )}
        </div>
      </div>
    </div>
  );
}
