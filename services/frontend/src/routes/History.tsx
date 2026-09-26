// History screen: every film, most recently active first. A film row opens its latest
// version; a disclosure lists every version, each linking to the screen for its phase.

import { Fragment, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { listPackages } from "@/api/client";
import { destination, groupByFilm } from "@/lib/films";
import { formatUsd, relativeTime, formatDateTime } from "@/lib/format";
import { Button, EmptyState, ErrorBanner, PhaseBadge, Spinner } from "@/components/ui";
import { Panel } from "@/components/Panel";
import { VersionBadge } from "@/components/versions/VersionBadge";

export default function History() {
  const navigate = useNavigate();
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const query = useQuery({
    queryKey: ["packages"],
    queryFn: listPackages,
    refetchInterval: 5000,
  });
  const films = query.data ? groupByFilm(query.data) : [];

  function toggle(filmId: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(filmId)) next.delete(filmId);
      else next.add(filmId);
      return next;
    });
  }

  return (
    <div className="mx-auto max-w-5xl">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">History</h1>
        <Button variant="secondary" onClick={() => query.refetch()} disabled={query.isFetching}>
          {query.isFetching ? "Refreshing..." : "Refresh"}
        </Button>
      </div>

      <div className="mt-6">
        {query.isLoading && <Spinner label="Loading runs..." />}
        {query.isError && <ErrorBanner title="Could not load runs" error={query.error} />}
        {query.data && films.length === 0 && (
          <EmptyState title="No runs yet">Submit a brief to get started.</EmptyState>
        )}

        {films.length > 0 && (
          <Panel>
            <table className="w-full text-left text-sm">
              <thead className="bg-surface-overlay text-xs uppercase tracking-wide text-fg-subtle">
                <tr>
                  <th className="w-8 px-2 py-2" aria-label="Versions" />
                  <th className="px-4 py-2 font-medium">Film</th>
                  <th className="px-4 py-2 font-medium">Last activity</th>
                  <th className="px-4 py-2 font-medium">Phase</th>
                  <th className="px-4 py-2 text-right font-medium">Cost</th>
                </tr>
              </thead>
              <tbody>
                {films.map((film) => {
                  const open = expanded.has(film.filmId);
                  const many = film.versions.length > 1;
                  return (
                    <Fragment key={film.filmId}>
                      <tr
                        className="cursor-pointer border-t transition-colors hover:bg-surface-overlay/50"
                        onClick={() => navigate(destination(film.latest))}
                      >
                        <td className="px-2 py-3 text-center">
                          {many && (
                            <button
                              type="button"
                              className="rounded px-1.5 text-fg-subtle hover:bg-surface-overlay hover:text-fg"
                              aria-expanded={open}
                              aria-label={open ? "Hide versions" : "Show versions"}
                              onClick={(event) => {
                                event.stopPropagation();
                                toggle(film.filmId);
                              }}
                            >
                              {open ? "v" : ">"}
                            </button>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <span className="font-medium text-fg">{film.latest.title}</span>
                            {many && <VersionBadge version={film.latest.version} />}
                          </div>
                          <div className="font-mono text-xs text-fg-subtle">
                            {film.latest.project_id}
                            {many && ` - ${film.versions.length} versions`}
                          </div>
                        </td>
                        <td
                          className="px-4 py-3 text-fg-muted"
                          title={formatDateTime(film.lastActivity)}
                        >
                          {relativeTime(film.lastActivity)}
                        </td>
                        <td className="px-4 py-3">
                          <PhaseBadge phase={film.latest.phase} />
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums">
                          {formatUsd(film.totalCostUsd)}
                        </td>
                      </tr>
                      {open &&
                        [...film.versions].reverse().map((version) => {
                          const parent = film.versions.find(
                            (v) => v.project_id === version.parent_project_id,
                          );
                          return (
                            <tr
                              key={version.project_id}
                              className="cursor-pointer border-t bg-surface/40 text-xs transition-colors hover:bg-surface-overlay/50"
                              onClick={() => navigate(destination(version))}
                            >
                              <td />
                              <td className="px-4 py-2 pl-8">
                                <div className="flex items-center gap-2">
                                  <VersionBadge version={version.version} />
                                  {parent && (
                                    <span className="text-fg-subtle">from v{parent.version}</span>
                                  )}
                                  <span className="font-mono text-fg-subtle">
                                    {version.project_id}
                                  </span>
                                </div>
                              </td>
                              <td
                                className="px-4 py-2 text-fg-muted"
                                title={formatDateTime(version.created_at)}
                              >
                                {relativeTime(version.created_at)}
                              </td>
                              <td className="px-4 py-2">
                                <PhaseBadge phase={version.phase} />
                              </td>
                              <td className="px-4 py-2 text-right tabular-nums">
                                {formatUsd(version.cost_usd)}
                              </td>
                            </tr>
                          );
                        })}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </Panel>
        )}
      </div>
    </div>
  );
}
