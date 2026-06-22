"""Typer CLI for the AI Film Pipeline (spec §12).

Commands:
  render-local  Dumb sequential driver — renders a hand-authored package
                end to end (topo walk -> adapters -> MinIO -> FFmpeg composite),
                with no Celery/scheduler/rate-limiter.
  seed-mock     Synthesize the placeholder assets the mock adapter points at and
                upload them to MinIO, so the free end-to-end mock run can composite.
  bench         Replay the flagship package at N worker counts -> CSV.
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

import typer

app = typer.Typer(help="AI Film Pipeline harness + sequential driver.")

# How long to wait between status polls for async providers (fal). Mock mode
# completes on the first poll, so this only bites real runs.
_POLL_INTERVAL_S = 3.0


# --------------------------------------------------------------------------
# Sequential driver
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


# The payload/extension/archival logic is the load-bearing per-node code shared
# with the Celery worker; it lives in ``worker.render`` so there's one source of
# truth. These thin shims keep the driver's call sites (and its tests) stable while
# delegating the real work. Imported lazily, matching this file's idiom.
def _ext_for(kind: str, url: str) -> str:
    from worker.render import ext_for

    return ext_for(kind, url)


def _build_payload(asset, pkg, provider_urls: dict[str, str]) -> dict:
    from worker.render import build_payload

    return build_payload(asset, pkg.meta, provider_urls)


async def _run_node(asset, pkg, store, provider_urls: dict[str, str]) -> float:
    """Generate one node, archive it to MinIO, and record its result on the asset."""
    from adapters import get_adapter
    from schema import NodeStatus
    from worker.render import archive_result, build_payload

    hint = asset.provider_hint or ""
    model = hint.split(":", 1)[1] if ":" in hint else ""
    adapter = get_adapter(hint)

    handle = await adapter.submit(model, build_payload(asset, pkg.meta, provider_urls))
    result = await adapter.poll(handle)
    while not result.done:
        await asyncio.sleep(_POLL_INTERVAL_S)
        result = await adapter.poll(handle)

    minio_url, provider_url = archive_result(result, store, pkg.project_id, asset.node_id, asset.type.value)
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
    """Render a package end to end with a dumb sequential driver."""
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
# Submit a package to the distributed fleet
# --------------------------------------------------------------------------
def _scheduler_base(scheduler_url: str | None) -> str:
    """Resolve the scheduler base URL: explicit flag > ``$SCHEDULER_URL`` > localhost.

    The harness is a host-side CLI (no container), so the default targets the
    published port rather than the in-network ``scheduler`` hostname.
    """
    url = scheduler_url or os.environ.get("SCHEDULER_URL") or "http://localhost:8001"
    return url.rstrip("/")


@app.command()
def submit(
    package: Path = typer.Option(..., exists=True, help="Production package JSON to submit."),
    approve: bool = typer.Option(
        False, "--approve", help="Approve immediately after ingest to kick the daemon."
    ),
    scheduler_url: str = typer.Option(
        None, help="Scheduler base URL (default: $SCHEDULER_URL or http://localhost:8001)."
    ),
) -> None:
    """POST a package to the scheduler (and optionally approve it): the entry
    that kicks the distributed run, the counterpart to ``render-local``."""
    import httpx
    from schema import ProductionPackage

    pkg = ProductionPackage.model_validate_json(package.read_text())  # fail fast on bad JSON
    base = _scheduler_base(scheduler_url)

    try:
        resp = httpx.post(
            f"{base}/packages",
            content=pkg.model_dump_json(),
            headers={"content-type": "application/json"},
            timeout=30.0,
        )
        resp.raise_for_status()
        project_id = resp.json()["project_id"]
        typer.echo(f"submitted {project_id} -> {base}")

        if approve:
            resp = httpx.post(f"{base}/packages/{project_id}/approve", timeout=30.0)
            resp.raise_for_status()
            typer.secho(f"approved {project_id} -> daemon will begin dispatch", fg=typer.colors.GREEN)
    except httpx.HTTPError as exc:
        typer.secho(f"submit failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc

    typer.echo(f"watch: {base}/packages/{project_id}/events")


# --------------------------------------------------------------------------
# Throughput benchmark (stub)
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
        # TODO: scale `worker` to n replicas via docker SDK, trigger the
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
