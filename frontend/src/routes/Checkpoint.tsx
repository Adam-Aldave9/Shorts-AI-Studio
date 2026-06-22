// Checkpoint screen (spec §4.3, §9.2) - the human-in-the-loop gate that cannot be
// cut. Left pane: a rendered summary of the package the scheduler is serving. Right
// pane: the raw package JSON in Monaco, schema-validated against GET /schema.
//
//   Approve -> POST /approve, then route to the live Status view.
//   Save    -> PUT /packages/{id}; the server re-runs the validator and returns 422
//              with the failing rules, shown inline.
//   Reject  -> discard (leave it unapproved) and go back to History.

import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Editor, { useMonaco } from "@monaco-editor/react";
import {
  approvePackage,
  getPackage,
  getPackageSchema,
  updatePackage,
  type ProductionPackage,
} from "@/api/client";
import { estimatedTotalUsd, shotDurationS, videoShots, voiceovers } from "@/lib/package";
import { formatDuration, formatUsd } from "@/lib/format";
import { Button, Card, ErrorBanner, Spinner, Stat } from "@/components/ui";

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

  const [draft, setDraft] = useState("");
  const [parseError, setParseError] = useState<string | null>(null);
  const initializedFor = useRef<string | null>(null);

  // Seed the editor once per project, then leave it under user control. The save
  // mutation re-seeds it from the server's canonical copy on success.
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
    onSuccess: () => navigate(`/status/${projectId}`),
  });

  const saveMutation = useMutation({
    mutationFn: (pkg: ProductionPackage) => updatePackage(projectId, pkg),
    onSuccess: (saved) => {
      queryClient.setQueryData(["package", projectId], saved);
      setDraft(JSON.stringify(saved, null, 2));
    },
  });

  function onSave() {
    setParseError(null);
    let parsed: ProductionPackage;
    try {
      parsed = JSON.parse(draft) as ProductionPackage;
    } catch (error) {
      setParseError(error instanceof Error ? error.message : "Invalid JSON");
      return;
    }
    saveMutation.mutate(parsed);
  }

  if (packageQuery.isLoading) return <Spinner label="Loading package..." />;
  if (packageQuery.isError) {
    return <ErrorBanner title="Could not load package" error={packageQuery.error} />;
  }
  const pkg = packageQuery.data;
  if (!pkg) return <ErrorBanner title="Package not found" error={`No package ${projectId}`} />;

  const shots = videoShots(pkg);
  const narration = voiceovers(pkg)[0]?.text ?? null;
  const busy = approveMutation.isPending || saveMutation.isPending;

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">{pkg.meta.title}</h1>
          <p className="font-mono text-xs text-neutral-400">{pkg.project_id}</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="danger" onClick={() => navigate("/history")} disabled={busy}>
            Reject
          </Button>
          <Button variant="secondary" onClick={onSave} disabled={busy}>
            {saveMutation.isPending ? "Saving..." : "Save changes"}
          </Button>
          <Button onClick={() => approveMutation.mutate()} disabled={busy}>
            {approveMutation.isPending ? "Approving..." : "Approve & run"}
          </Button>
        </div>
      </div>

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
              <dt className="text-neutral-500">Duration</dt>
              <dd className="col-span-2">{formatDuration(pkg.meta.target_duration_s)}</dd>
              <dt className="text-neutral-500">Style</dt>
              <dd className="col-span-2">{pkg.meta.style}</dd>
              <dt className="text-neutral-500">Aspect</dt>
              <dd className="col-span-2">{pkg.meta.aspect_ratio}</dd>
              <dt className="text-neutral-500">Premise</dt>
              <dd className="col-span-2 text-neutral-700">{pkg.meta.premise}</dd>
            </dl>
          </Card>

          {narration && (
            <Card>
              <div className="text-xs uppercase tracking-wide text-neutral-500">Narration</div>
              <p className="mt-2 whitespace-pre-wrap text-sm text-neutral-700">{narration}</p>
            </Card>
          )}

          <div className="overflow-hidden rounded-lg border bg-white shadow-sm">
            <div className="border-b px-4 py-2 text-xs uppercase tracking-wide text-neutral-500">
              Shot list
            </div>
            <div className="max-h-80 overflow-auto">
              <table className="w-full text-left text-sm">
                <thead className="sticky top-0 bg-neutral-50 text-xs uppercase tracking-wide text-neutral-500">
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
                      <td className="px-4 py-2 font-mono text-xs text-neutral-500">{shot.node_id}</td>
                      <td className="px-4 py-2 text-neutral-700">
                        <div className="line-clamp-2">{shot.prompt ?? "-"}</div>
                        {shot.provider_hint && (
                          <div className="font-mono text-[10px] text-neutral-400">
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

        {/* Right: raw JSON editor */}
        <div className="space-y-3">
          {parseError && <ErrorBanner title="Invalid JSON" error={parseError} />}
          {saveMutation.isError && (
            <ErrorBanner title="Validation failed" error={saveMutation.error} />
          )}
          {approveMutation.isError && (
            <ErrorBanner title="Could not approve" error={approveMutation.error} />
          )}
          {saveMutation.isSuccess && !saveMutation.isPending && (
            <div className="rounded-md border border-green-300 bg-green-50 px-4 py-2 text-sm text-green-800">
              Saved and re-validated.
            </div>
          )}
          <div className="overflow-hidden rounded-lg border">
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
              }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
