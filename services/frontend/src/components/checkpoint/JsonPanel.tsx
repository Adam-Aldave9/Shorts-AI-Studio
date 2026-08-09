// The raw-JSON escape hatch. Monaco is confined to this component so its CDN bundle is not
// fetched until the tab is opened.

import { useCallback, useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import Editor, { useMonaco } from "@monaco-editor/react";
import { getPackageSchema } from "@/api/client";
import { Button, ErrorBanner } from "@/components/ui";

// Monaco's JSON `jsonDefaults` isn't surfaced by the loader's slim types, so narrow to
// just the method we call.
interface JsonLanguageDefaults {
  setDiagnosticsOptions(options: {
    validate?: boolean;
    schemas?: Array<{ uri: string; fileMatch?: string[]; schema?: unknown }>;
  }): void;
}

// Hoisted: a fresh object here would make Monaco call `editor.updateOptions()` on every
// re-render of the host.
const EDITOR_OPTIONS = {
  minimap: { enabled: false },
  fontSize: 12,
  scrollBeyondLastLine: false,
  tabSize: 2,
} as const;

export function JsonPanel({
  value,
  readOnly,
  parseError,
  onChange,
  onDiscard,
}: {
  value: string;
  readOnly: boolean;
  parseError: string | null;
  onChange: (value: string) => void;
  onDiscard: () => void;
}) {
  const monaco = useMonaco();
  const schemaQuery = useQuery({ queryKey: ["schema"], queryFn: getPackageSchema });

  useEffect(() => {
    if (!monaco || !schemaQuery.data) return;
    const json = (monaco.languages as unknown as { json?: { jsonDefaults: JsonLanguageDefaults } })
      .json;
    json?.jsonDefaults.setDiagnosticsOptions({
      validate: true,
      schemas: [{ uri: "afp://package.schema.json", fileMatch: ["*"], schema: schemaQuery.data }],
    });
  }, [monaco, schemaQuery.data]);

  // Stable, or Monaco disposes and re-subscribes the model-content listener every render.
  const onEditorChange = useCallback(
    (next: string | undefined) => onChange(next ?? ""),
    [onChange],
  );
  const options = useMemo(() => ({ ...EDITOR_OPTIONS, readOnly }), [readOnly]);

  return (
    <div className="space-y-3">
      {parseError && (
        <div className="space-y-2">
          <ErrorBanner title="Invalid JSON" error={parseError} />
          <Button variant="ghost" onClick={onDiscard}>
            Discard JSON edits
          </Button>
        </div>
      )}
      <div className="overflow-hidden rounded-xl border">
        <Editor
          height="70vh"
          defaultLanguage="json"
          theme="vs-dark"
          value={value}
          onChange={onEditorChange}
          options={options}
        />
      </div>
    </div>
  );
}
