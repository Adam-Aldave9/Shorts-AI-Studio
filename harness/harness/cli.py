"""Typer CLI for the AI Film Pipeline (spec §12).

Commands:
  render-local  Phase 1 dumb sequential driver — renders a hand-authored package
                end to end (topo walk -> adapters -> MinIO -> FFmpeg composite),
                with no Celery/scheduler/rate-limiter. The Phase 1 deliverable.
  seed-mock     Synthesize the placeholder assets the mock adapter points at and
                upload them to MinIO, so the free end-to-end mock run can composite.
  bench         (Phase 4) Replay the flagship package at N worker counts -> CSV.
  critical-path Print the DAG critical path (the theoretical render-time floor).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import typer

app = typer.Typer(help="AI Film Pipeline harness + Phase 1 sequential driver.")

# How long to wait between status polls for async providers (fal). Mock mode
# completes on the first poll, so this only bites real runs.
_POLL_INTERVAL_S = 3.0


# --------------------------------------------------------------------------
# Phase 1 — sequential driver
# --------------------------------------------------------------------------
def _topo_order(pkg) -> list:
    """Return assets in dependency order (a dependency precedes its dependents)."""
    by_id = {a.node_id: a for a in pkg.assets}
    order: list[str] = []
    perm: set[str] = set()
    temp: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in perm:
            return
        if node_id in temp:
            raise ValueError(f"dependency cycle involving {node_id!r}")
        temp.add(node_id)
        asset = by_id.get(node_id)
        if asset is not None:
            for dep in asset.depends_on:
                if dep in by_id:
                    visit(dep)
        temp.discard(node_id)
        perm.add(node_id)
        order.append(node_id)

    for asset in pkg.assets:
        visit(asset.node_id)
    return [by_id[n] for n in order]


def _ext_for(kind: str, url: str) -> str:
    """Pick a file extension from the result URL, falling back per asset type."""
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".webm", ".mov", ".mp3", ".wav", ".m4a"}:
        return suffix
    return {"image": ".png", "video": ".mp4", "voiceover": ".mp3"}[kind]


def _build_payload(asset, pkg, provider_urls: dict[str, str]) -> dict:
    """Uniform payload understood by both the real adapters and the mock adapter.

    ``asset_type`` drives the mock; the real adapters read the type-specific fields.
    For i2v we feed the **upstream provider URL** of the reference image (fal fetches
    ``image_url`` over the public internet), not the MinIO copy.
    """
    kind = asset.type.value
    payload: dict = {"asset_type": kind}
    if kind == "image":
        payload.update(prompt=asset.prompt or "", width=asset.spec.get("width"), height=asset.spec.get("height"))
    elif kind == "video":
        image_url = next(
            (provider_urls[r] for r in asset.reference_image_ids if r in provider_urls), None
        )
        payload.update(prompt=asset.prompt or "", duration=asset.spec.get("duration_s"), image_url=image_url)
    elif kind == "voiceover":
        payload.update(text=asset.text or "", voice_id=asset.spec.get("voice_id") or pkg.meta.narration_voice_id)
    return payload


async def _run_node(asset, pkg, store, provider_urls: dict[str, str]) -> float:
    """Generate one node, archive it to MinIO, and record its result on the asset."""
    from adapters import get_adapter
    from schema import NodeStatus

    hint = asset.provider_hint or ""
    model = hint.split(":", 1)[1] if ":" in hint else ""
    adapter = get_adapter(hint)

    handle = await adapter.submit(model, _build_payload(asset, pkg, provider_urls))
    result = await adapter.poll(handle)
    while not result.done:
        await asyncio.sleep(_POLL_INTERVAL_S)
        result = await adapter.poll(handle)

    pid = pkg.project_id
    if result.content is not None:
        # Inline bytes (ElevenLabs): the driver owns archival.
        minio_url = store.put_bytes(f"{pid}/{asset.node_id}.mp3", result.content, "audio/mpeg")
        provider_url = minio_url
    elif result.asset_url.startswith("s3://"):
        # Mock placeholder already lives in object storage — pass through.
        minio_url = provider_url = result.asset_url
    else:
        # Real provider http(s) URL: copy into MinIO, but keep the provider URL for
        # any downstream i2v node that needs a public reference image.
        ext = _ext_for(asset.type.value, result.asset_url)
        minio_url = store.put_from_url(f"{pid}/{asset.node_id}{ext}", result.asset_url)
        provider_url = result.asset_url

    provider_urls[asset.node_id] = provider_url
    asset.asset_url = minio_url
    asset.status = NodeStatus.SUCCEEDED
    asset.actual_cost_usd = result.cost_usd
    return result.cost_usd


async def _generate_all(order, pkg, store, provider_urls: dict[str, str]) -> None:
    for asset in order:
        if not asset.provider_hint:
            raise typer.BadParameter(f"node {asset.node_id!r} has no provider_hint")
        cost = await _run_node(asset, pkg, store, provider_urls)
        typer.echo(f"  [ok] {asset.node_id:<18} {asset.type.value:<9} ${cost:.4f}")


@app.command(name="render-local")
def render_local(
    package: Path = typer.Option(..., exists=True, help="Production package JSON."),
    mock: bool = typer.Option(False, "--mock", help="Force MOCK mode ($0, placeholder assets)."),
) -> None:
    """Render a package end to end with a dumb sequential driver (Phase 1)."""
    from adapters import ProviderError
    from adapters.registry import mock_enabled
    from schema import ProductionPackage
    from storage import Storage

    if mock:
        os.environ["MOCK"] = "true"

    pkg = ProductionPackage.model_validate_json(package.read_text())
    store = Storage()
    store.ensure_bucket()
    order = _topo_order(pkg)
    typer.echo(
        f"render-local: {pkg.project_id} — {len(order)} nodes, "
        f"mock={mock_enabled()}, bucket={store.bucket}"
    )

    provider_urls: dict[str, str] = {}
    try:
        asyncio.run(_generate_all(order, pkg, store, provider_urls))
    except ProviderError as exc:
        typer.secho(f"provider error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc

    try:
        from compositor.render import composite_package
    except ImportError as exc:
        typer.secho(
            "compositor not importable — install it editable too: "
            "pip install -e compositor",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(1) from exc

    final_url = composite_package(pkg, store)

    total = sum(a.actual_cost_usd or 0.0 for a in pkg.assets)
    out_path = package.with_suffix(".rendered.json")
    out_path.write_text(pkg.model_dump_json(indent=2))

    typer.echo("")
    typer.secho(f"final cut: {final_url}", fg=typer.colors.GREEN)
    typer.echo(f"total cost: ${total:.4f} across {len(order)} nodes")
    typer.echo(f"rendered package written to {out_path}")


# --------------------------------------------------------------------------
# Mock-asset seeding
# --------------------------------------------------------------------------
def _ffmpeg(args: list[str]) -> None:
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed (exit {proc.returncode}): {proc.stderr[-1000:]}")


@app.command(name="seed-mock")
def seed_mock() -> None:
    """Synthesize the mock adapter's placeholder assets and upload them to MinIO."""
    from storage import Storage

    if shutil.which("ffmpeg") is None:
        typer.secho("ffmpeg not found on PATH; required to synthesize placeholders", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    store = Storage()
    store.ensure_bucket()

    with tempfile.TemporaryDirectory(prefix="afp_seed_") as tmp:
        tmpdir = Path(tmp)
        png, mp4, mp3 = tmpdir / "placeholder.png", tmpdir / "placeholder.mp4", tmpdir / "placeholder.mp3"
        # A single test-pattern frame, a 3s test-pattern clip, a 90s sine tone.
        _ffmpeg(["-f", "lavfi", "-i", "testsrc=size=1280x720:rate=1", "-frames:v", "1", str(png)])
        _ffmpeg(["-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30:duration=3",
                 "-pix_fmt", "yuv420p", "-c:v", "libx264", "-t", "3", str(mp4)])
        _ffmpeg(["-f", "lavfi", "-i", "sine=frequency=220:duration=90",
                 "-c:a", "libmp3lame", "-q:a", "5", str(mp3)])

        for path, key, ctype in (
            (png, "_mock/placeholder.png", "image/png"),
            (mp4, "_mock/placeholder.mp4", "video/mp4"),
            (mp3, "_mock/placeholder.mp3", "audio/mpeg"),
        ):
            url = store.put_bytes(key, path.read_bytes(), ctype)
            typer.echo(f"  seeded {url}")

    typer.secho("mock placeholders seeded", fg=typer.colors.GREEN)


# --------------------------------------------------------------------------
# Phase 4 — throughput benchmark (unchanged stub)
# --------------------------------------------------------------------------
@app.command()
def bench(
    package: Path = typer.Option(..., exists=True, help="Flagship package JSON."),
    workers: str = typer.Option("1,2,4,8,16", help="Comma-separated worker counts."),
    out: Path = typer.Option(Path("results.csv"), help="CSV output path."),
) -> None:
    """Replay the package at each worker count in mock mode; emit a CSV."""
    counts = [int(w) for w in workers.split(",")]
    pkg = json.loads(package.read_text())
    typer.echo(f"Loaded package {pkg.get('project_id', '?')} with {len(pkg.get('assets', []))} nodes")
    for n in counts:
        # TODO(week4): scale `worker` to n replicas via docker SDK, trigger the
        # run in MOCK mode, collect per-node start/end timestamps + queue depth.
        typer.echo(f"[stub] would run package at {n} worker(s)")
    typer.echo(f"[stub] would write {out}")


@app.command(name="critical-path")
def critical_path(package: Path = typer.Argument(..., exists=True)) -> None:
    """Print the DAG critical path — the theoretical render-time floor (Graph B)."""
    from schema import ProductionPackage

    pkg = ProductionPackage.model_validate_json(package.read_text())
    memo: dict[str, float] = {}
    by_id = {a.node_id: a for a in pkg.assets}

    def cost(node_id: str) -> float:
        if node_id in memo:
            return memo[node_id]
        a = by_id[node_id]
        dep = max((cost(d) for d in a.depends_on if d in by_id), default=0.0)
        memo[node_id] = float(a.spec.get("duration_s", 1.0)) + dep
        return memo[node_id]

    floor = max((cost(n) for n in by_id), default=0.0)
    typer.echo(f"critical path: {floor:.1f}s")


if __name__ == "__main__":
    app()
