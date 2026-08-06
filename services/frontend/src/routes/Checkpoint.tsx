// Checkpoint screen — the human-in-the-loop gate. Left: a read-only
// summary of the package the scheduler is serving. Right: two editors over the same
// package — a structured Form (default) and the raw JSON in Monaco (schema-validated).
// Approve auto-saves pending edits, then routes to Status. Once the run starts the package
// locks (GET .../status `approved`): controls go read-only and a stale edit/approve 409s.

import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Editor, { useMonaco } from "@monaco-editor/react";
import {
  approvePackage,
  getPackage,
  getPackageSchema,
  getPackageStatus,
  isConflict,
  updatePackage,
  type ProductionPackage,
} from "@/api/client";
import { Button, ErrorBanner, Spinner, SuccessBanner, cn } from "@/components/ui";
import { PackageSummary } from "@/components/PackageSummary";
import PackageEditForm from "@/components/PackageEditForm";

// Monaco's JSON `jsonDefaults` isn't surfaced by the loader's slim types, so narrow to
// just the method we call.
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

  // The form's merged package + dirtiness, kept in a ref so keystrokes don't re-render
  // Checkpoint. The cached package stays the source of truth; this is a live view.
  const formStateRef = useRef<{ merged: ProductionPackage; dirty: boolean }>({
    merged: packageQuery.data ?? ({} as ProductionPackage),
    dirty: false,
  });
  const onFormDraftChange = useCallback((merged: ProductionPackage, dirty: boolean) => {
    formStateRef.current = { merged, dirty };
  }, []);

  // Seed Monaco once per project, then leave it under user control; the save mutation
  // re-seeds it from the server's canonical copy on success.
  useEffect(() => {
    if (packageQuery.data && initializedFor.current !== projectId) {
      setDraft(JSON.stringify(packageQuery.data, null, 2));
      initializedFor.current = projectId;
    }
  }, [packageQuery.data, projectId]);

  // Wire the served JSON schema into Monaco for live validation feedback.
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
      if (isConflict(error)) {
        queryClient.invalidateQueries({ queryKey: ["packageStatus", projectId] });
      }
    },
  });

  const saveMutation = useMutation({
    mutationFn: (pkg: ProductionPackage) => updatePackage(projectId, pkg),
    onSuccess: (saved) => {
      // Re-seed both views from the server's canonical copy: the identity change re-seeds
      // the form, and we rewrite the Monaco draft explicitly.
      queryClient.setQueryData(["package", projectId], saved);
      setDraft(JSON.stringify(saved, null, 2));
    },
    onError: (error) => {
      if (isConflict(error)) {
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

  const busy = approveMutation.isPending || saveMutation.isPending;

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
  // validator banner. mutateAsync so approve only runs once the save succeeds.
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

  // Switching views carries pending edits across so neither view silently drops them; the
  // visible editor is always the authoritative one.
  function switchToAdvanced() {
    setDraft(JSON.stringify(formStateRef.current.merged, null, 2));
    setAdvanced(true);
  }
  function switchToForm() {
    // The form re-seeds from the cached package, so commit the Monaco edits there first;
    // block the switch on invalid JSON.
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
        <PackageSummary pkg={pkg} />

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
