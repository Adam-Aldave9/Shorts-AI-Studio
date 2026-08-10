// Result screen: the final cut, then the planning draft it came from — synopsis, script and
// shot list — so a finished film can be read against what was planned. `final_url` lives in
// live run state rather than the package, so it comes from the SSE stream and not the
// package GET.

import { useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getPackage } from "@/api/client";
import { useStatusStream } from "@/hooks/useStatusStream";
import { actualTotalUsd, scenes, timelineByNode, videoShots } from "@/lib/package";
import { formatDuration, formatUsd } from "@/lib/format";
import { EmptyState, ErrorBanner, Spinner, Stat, Tabs } from "@/components/ui";
import { CostPanel } from "@/components/result/CostPanel";
import { ShotsPanel } from "@/components/result/ShotsPanel";
import { StoryPanel } from "@/components/result/StoryPanel";
import type { ResultTab } from "@/components/result/tabs";

export default function Result() {
  const { projectId = "" } = useParams();
  // Close the stream once the run completes so a finished run doesn't reconnect-loop.
  const event = useStatusStream(projectId, true);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [tab, setTab] = useState<ResultTab>("story");

  const packageQuery = useQuery({
    queryKey: ["package", projectId],
    queryFn: () => getPackage(projectId),
    enabled: Boolean(projectId),
  });

  if (packageQuery.isLoading) return <Spinner label="Loading result..." />;
  if (packageQuery.isError) {
    return <ErrorBanner title="Could not load this package" error={packageQuery.error} />;
  }

  const pkg = packageQuery.data;
  const finalUrl = event?.final_url ?? null;
  const totalCost = event?.cost_usd ?? (pkg ? actualTotalUsd(pkg) : 0);

  const seekToShot = (nodeId: string) => {
    const video = videoRef.current;
    const start = pkg && timelineByNode(pkg).get(nodeId)?.in_s;
    if (!video || start == null) return;
    video.currentTime = start;
    void video.play().catch(() => undefined);
  };

  const tabs = [
    { id: "story" as const, label: "Story", badge: pkg ? scenes(pkg).length || undefined : undefined },
    { id: "shots" as const, label: "Shots", badge: pkg ? videoShots(pkg).length : undefined },
    { id: "cost" as const, label: "Cost" },
  ];

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">{pkg?.meta.title ?? "Result"}</h1>
          <p className="font-mono text-xs text-fg-subtle">{projectId}</p>
        </div>
        <Link className="text-sm text-accent-soft underline hover:text-accent" to="/history">
          Back to history
        </Link>
      </div>

      {finalUrl ? (
        <div className="space-y-2">
          <video
            ref={videoRef}
            className="w-full rounded-xl border bg-black"
            src={finalUrl}
            controls
          />
          <a
            className="text-sm text-accent-soft underline hover:text-accent"
            href={finalUrl}
            download
          >
            Download MP4
          </a>
        </div>
      ) : (
        <EmptyState title="Render not finished yet">
          The final cut is not available.{" "}
          <Link className="underline" to={`/status/${projectId}`}>
            Watch execution
          </Link>{" "}
          and this page will fill in when it completes.
        </EmptyState>
      )}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Stat label="Total cost" value={formatUsd(totalCost)} />
        <Stat
          label="Critical path"
          value={event ? formatDuration(event.critical_path_s) : "-"}
          hint="theoretical floor"
        />
        <Stat label="Shots" value={pkg ? videoShots(pkg).length : 0} />
      </div>

      {pkg && (
        <div className="space-y-4">
          <Tabs tabs={tabs} active={tab} onChange={setTab} />
          {tab === "story" && <StoryPanel pkg={pkg} onSeek={seekToShot} />}
          {tab === "shots" && <ShotsPanel pkg={pkg} />}
          {tab === "cost" && <CostPanel pkg={pkg} />}
        </div>
      )}
    </div>
  );
}
