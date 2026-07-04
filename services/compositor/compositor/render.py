"""The compositor render logic (spec §8), as a pure function with no Celery.

``composite_package`` pulls every clip + the narration from object storage, builds
one FFmpeg filtergraph that scales/pads each clip to the target resolution, trims
it to its timeline slot, concatenates the clips in order, lays the narration over
the top, and encodes a single H.264/AAC MP4 back to object storage.

It is deliberately plain: no LUT/color grade (spec §8 allows a single
LUT later), one narration track. The Celery task in ``tasks.py`` is a thin wrapper
over this; the sequential driver calls it directly.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from schema import AssetType, ProductionPackage
from storage import Storage

log = logging.getLogger("compositor.render")

# Target output frame rate. Clips are normalized to this so concat is seamless.
_FPS = 30


def _resolution(aspect_ratio: str) -> tuple[int, int]:
    """Map an aspect ratio to a concrete 720-line resolution."""
    return {
        "16:9": (1280, 720),
        "9:16": (720, 1280),
        "1:1": (720, 720),
        "4:3": (960, 720),
    }.get(aspect_ratio, (1280, 720))


def composite_package(pkg: ProductionPackage, storage: Storage | None = None) -> str:
    """Render ``pkg``'s timeline to a final MP4 in object storage; return its URL."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found on PATH; it is required to render")

    storage = storage or Storage()
    width, height = _resolution(pkg.meta.aspect_ratio)

    # Split the timeline into the ordered video track and the (single) audio track.
    video_entries = sorted(
        (e for e in pkg.timeline if _is_type(pkg, e.node_id, AssetType.VIDEO)),
        key=lambda e: e.in_s,
    )
    audio_entry = next((e for e in pkg.timeline if e.audio_track is not None), None)
    if not video_entries:
        raise RuntimeError("timeline has no video clips to composite")

    with tempfile.TemporaryDirectory(prefix="afp_render_") as tmp:
        tmpdir = Path(tmp)
        # Cache downloads by source URL so mock mode (every clip is the same
        # placeholder) doesn't pull the same object dozens of times.
        local: dict[str, Path] = {}

        def fetch(node_id: str, suffix: str) -> Path:
            asset = pkg.asset_by_id(node_id)
            if asset is None or not asset.asset_url:
                raise RuntimeError(f"node {node_id!r} has no asset_url to composite")
            if asset.asset_url not in local:
                dest = tmpdir / f"src_{len(local)}{suffix}"
                local[asset.asset_url] = storage.get_to_path(asset.asset_url, dest)
            return local[asset.asset_url]

        inputs: list[str] = []
        filters: list[str] = []
        for i, entry in enumerate(video_entries):
            clip = fetch(entry.node_id, ".mp4")
            inputs += ["-i", str(clip)]
            dur = max(entry.out_s - entry.in_s, 0.04)
            # scale (keep AR) -> pad to frame -> square pixels -> fixed fps -> trim.
            filters.append(
                f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,"
                f"fps={_FPS},trim=duration={dur:.3f},setpts=PTS-STARTPTS[v{i}]"
            )
        concat_src = "".join(f"[v{i}]" for i in range(len(video_entries)))
        filters.append(f"{concat_src}concat=n={len(video_entries)}:v=1:a=0[outv]")

        maps = ["-map", "[outv]"]
        if audio_entry is not None:
            narration = fetch(audio_entry.node_id, ".mp3")
            audio_idx = len(video_entries)
            inputs += ["-i", str(narration)]
            filters.append(f"[{audio_idx}:a]aresample=48000,asetpts=PTS-STARTPTS[outa]")
            maps += ["-map", "[outa]"]

        out_path = tmpdir / "final.mp4"
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            *inputs,
            "-filter_complex", ";".join(filters),
            *maps,
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "20",
        ]
        if audio_entry is not None:
            cmd += ["-c:a", "aac", "-b:a", "192k"]
        cmd += ["-movflags", "+faststart", str(out_path)]

        log.info("ffmpeg compositing %d clips -> %s", len(video_entries), out_path.name)
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg failed (exit {proc.returncode}): {proc.stderr[-2000:]}")

        key = f"{pkg.project_id}/final.mp4"
        url = storage.put_bytes(key, out_path.read_bytes(), "video/mp4")
        log.info("final cut uploaded: %s", url)
        return url


def _is_type(pkg: ProductionPackage, node_id: str, asset_type: AssetType) -> bool:
    asset = pkg.asset_by_id(node_id)
    return asset is not None and asset.type == asset_type
