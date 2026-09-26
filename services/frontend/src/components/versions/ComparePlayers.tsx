// The parent and current cuts side by side, playable in lockstep.

import { useRef } from "react";
import { finalCutUrl } from "@/api/client";
import { Button, Card } from "@/components/ui";
import { VersionBadge } from "./VersionBadge";

export function ComparePlayers({
  left,
  right,
  onClose,
}: {
  left: { projectId: string; version: number };
  right: { projectId: string; version: number };
  onClose: () => void;
}) {
  const refs = [useRef<HTMLVideoElement>(null), useRef<HTMLVideoElement>(null)];
  const each = (fn: (video: HTMLVideoElement) => void) =>
    refs.forEach((ref) => ref.current && fn(ref.current));

  return (
    <Card className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">Compare versions</h2>
        <div className="flex gap-2">
          <Button
            variant="secondary"
            onClick={() =>
              each((video) => {
                video.currentTime = 0;
                void video.play().catch(() => undefined);
              })
            }
          >
            Play both
          </Button>
          <Button variant="secondary" onClick={() => each((video) => video.pause())}>
            Pause both
          </Button>
          <Button variant="ghost" onClick={onClose}>
            Close
          </Button>
        </div>
      </div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {[left, right].map((side, index) => (
          <div key={side.projectId} className="space-y-1">
            <VersionBadge version={side.version} />
            <video
              ref={refs[index]}
              className="w-full rounded-lg border bg-black"
              src={finalCutUrl(side.projectId)}
              controls
              preload="metadata"
            />
          </div>
        ))}
      </div>
    </Card>
  );
}
