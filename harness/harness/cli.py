"""Typer CLI for the AI Film Pipeline (spec §12).

Commands:
  render-local  Dumb sequential driver — renders a hand-authored package
                end to end (topo walk -> adapters -> MinIO -> FFmpeg composite),
                with no Celery/scheduler/rate-limiter.
  seed-mock     Synthesize the placeholder assets the mock adapter points at and
                upload them to MinIO, so the free end-to-end mock run can composite.
  bench         Replay the flagship package at N worker counts -> CSV.
  critical-path Print both DAG floors: the content critical path (spec
                durations) and the mock render-time floor (latency-weighted).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import time
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


# Thin shims over ``worker.render`` so the driver and Celery worker share one
# per-node implementation. Lazy import matches this file's idiom.
def _ext_for(kind: str, url: str) -> str:
    from worker.render import ext_for

    return ext_for(kind, url)


def _build_payload(asset, pkg, provider_urls: dict[str, str]) -> dict:
    from worker.render import build_payload

    return build_payload(asset, pkg.meta, provider_urls)


def _latency_weight(asset) -> float:
    """Per-node mock latency by asset type — the weight that turns the critical
    path into the render-time floor (Graph B). Sourced from
    ``adapters.mock._PROFILES`` so it never drifts from what the mock sleeps."""
    from adapters.mock import _PROFILES

    mean_latency, _unit_cost = _PROFILES[asset.type.value]
    return mean_latency


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
# Throughput benchmark (spec §12 — the headline graphs)
# --------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[2]
_COMPOSE_FILE = "docker-compose.yml"

# Canonical CSV schema — raw per-trial rows; the notebook averages and draws
# error bars over the high-variance mock latency.
_BENCH_COLUMNS = [
    "worker_count",
    "trial",
    "project_id",
    "exec_wall_clock_s",
    "total_wall_clock_s",
    "cost_usd",
    "critical_path_latency_s",
    "n_nodes",
]


def _compose(args: list[str]) -> subprocess.CompletedProcess:
    """Run ``docker compose`` from the repo root, reusing the existing service
    definition.

    ``MOCK`` is forced on (unless already set) so a recreated worker keeps mock
    mode: ``up -d --scale`` recreates the worker, and compose resolves its
    ``${MOCK:-false}`` from this process's env — without it the fresh worker
    defaults to real providers and dead-letters every node."""
    env = {**os.environ}
    env.setdefault("MOCK", "true")
    return subprocess.run(
        ["docker", "compose", "-f", _COMPOSE_FILE, *args],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )


def _running_workers() -> int:
    """How many ``worker`` containers are currently running."""
    proc = _compose(["ps", "--status", "running", "-q", "worker"])
    if proc.returncode != 0:
        return 0
    return sum(1 for line in proc.stdout.splitlines() if line.strip())


def _scale_workers(n: int, settle_s: float, ready_timeout_s: float = 60.0) -> None:
    """Scale the ``worker`` service to ``n`` replicas and wait until they're up.

    Compose reconciles the running count, then we poll until ``n`` workers report
    running and let Celery settle so the fleet has connected to the broker before
    T0 — the timing is honest only if the workers exist when we approve.
    """
    proc = _compose(["up", "-d", "--scale", f"worker={n}", "worker"])
    if proc.returncode != 0:
        typer.secho(
            f"docker compose --scale worker={n} failed:\n{proc.stderr.strip()}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(1)
    deadline = time.monotonic() + ready_timeout_s
    while time.monotonic() < deadline and _running_workers() < n:
        time.sleep(1.0)
    if settle_s > 0:
        time.sleep(settle_s)


def _run_trial(
    base: str, package: Path, n: int, trial: int, floor: float, timeout_s: float
) -> dict:
    """One isolated run at ``n`` workers, stopwatched over SSE.

    The ``project_id`` is rewritten to ``p_bench_w{n}_t{trial}`` so each trial is
    independent (no Redis/PG collisions). T0 is approve; the SSE stream is the
    clock: T1 at ``phase == compositing`` (execution fan-out done, excluding the
    constant compositor tail), end-to-end at ``complete``.
    """
    import httpx
    from state import PHASE_COMPOSITING

    pkg_dict = json.loads(package.read_text())
    project_id = f"p_bench_w{n}_t{trial}"
    pkg_dict["project_id"] = project_id
    n_nodes = len(pkg_dict.get("assets", []))

    httpx.post(
        f"{base}/packages",
        content=json.dumps(pkg_dict),
        headers={"content-type": "application/json"},
        timeout=30.0,
    ).raise_for_status()

    t0 = time.monotonic()  # T0 = approve
    httpx.post(f"{base}/packages/{project_id}/approve", timeout=30.0).raise_for_status()

    exec_t: float | None = None
    total_t: float | None = None
    cost = 0.0
    last_phase: str | None = None
    # Frames arrive every ~1 s (the daemon's SSE generator), so a short read timeout
    # is safe; the per-trial guard below caps the whole run.
    sse_timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
    with httpx.stream(
        "GET", f"{base}/packages/{project_id}/events", timeout=sse_timeout
    ) as stream:
        for line in stream.iter_lines():
            if not line.startswith("data:"):
                continue
            frame = json.loads(line[len("data:"):].strip())
            last_phase = frame.get("phase")
            cost = frame.get("cost_usd", cost)
            if last_phase == PHASE_COMPOSITING and exec_t is None:
                exec_t = time.monotonic() - t0
            if frame.get("complete"):
                total_t = time.monotonic() - t0
                break
            if time.monotonic() - t0 > timeout_s:
                typer.secho(
                    f"    trial w={n} t={trial} exceeded {timeout_s:.0f}s guard "
                    f"(last phase={last_phase})",
                    fg=typer.colors.YELLOW,
                    err=True,
                )
                break

    if total_t is None:  # stream closed on a non-complete terminal phase, or guard hit
        total_t = time.monotonic() - t0
        if last_phase != "complete":
            typer.secho(
                f"    trial w={n} t={trial} ended in phase={last_phase}, not complete",
                fg=typer.colors.YELLOW,
                err=True,
            )
    if exec_t is None:  # never observed a compositing frame -> fold into total
        exec_t = total_t

    return {
        "worker_count": n,
        "trial": trial,
        "project_id": project_id,
        "exec_wall_clock_s": round(exec_t, 3),
        "total_wall_clock_s": round(total_t, 3),
        "cost_usd": cost,
        "critical_path_latency_s": floor,
        "n_nodes": n_nodes,
    }


def _dry_row(package: Path, n: int, trial: int, floor: float) -> dict:
    """A schema-correct row with empty timings — lets ``--dry-run`` exercise the CSV
    schema (verification step 2) with no docker fleet or live scheduler."""
    pkg_dict = json.loads(package.read_text())
    return {
        "worker_count": n,
        "trial": trial,
        "project_id": f"p_bench_w{n}_t{trial}",
        "exec_wall_clock_s": None,
        "total_wall_clock_s": None,
        "cost_usd": None,
        "critical_path_latency_s": floor,
        "n_nodes": len(pkg_dict.get("assets", [])),
    }


@app.command()
def bench(
    package: Path = typer.Option(..., exists=True, help="Flagship package JSON."),
    workers: str = typer.Option("1,2,4,8,16", help="Comma-separated worker counts."),
    trials: int = typer.Option(3, help="Trials per worker count (averaged in the notebook)."),
    out: Path = typer.Option(Path("results.csv"), help="CSV output path."),
    scheduler_url: str = typer.Option(
        None, help="Scheduler base URL (default: $SCHEDULER_URL or http://localhost:8001)."
    ),
    settle_s: float = typer.Option(
        5.0, help="Seconds to let freshly-scaled workers connect to the broker before T0."
    ),
    timeout_s: float = typer.Option(1800.0, help="Per-trial wall-clock guard (seconds)."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Skip docker scaling + the live run; emit the CSV schema only."
    ),
) -> None:
    """Replay the flagship at each worker count (mock mode) and emit a CSV — the
    data behind the two throughput graphs (spec §12). ``$0`` throughout.

    Prereqs: the stack is up with ``MOCK=true`` and ``seed-mock`` has run. For each
    worker count N and trial t, the run is isolated to ``p_bench_w{N}_t{t}``, the
    ``worker`` service is scaled to N, and the SSE stream is the stopwatch (see
    ``_run_trial``). Raw per-trial rows are kept so the notebook can average and
    draw error bars over the high-variance mock latency."""
    import pandas as pd
    from schema import ProductionPackage

    from scheduler.dag import Dag

    counts = [int(w) for w in workers.split(",")]
    base = _scheduler_base(scheduler_url)
    # The latency-weighted floor — the Graph B reference line, carried into every
    # row so the notebook reads it directly without recomputing.
    floor = Dag(ProductionPackage.model_validate_json(package.read_text())).critical_path_estimate(
        weight=_latency_weight
    )
    typer.echo(
        f"bench: {package.name} -> {out}  "
        f"(counts={counts}, trials={trials}, floor={floor:.1f}s, base={base}"
        f"{', dry-run' if dry_run else ''})"
    )

    rows: list[dict] = []
    try:
        for n in counts:
            if not dry_run:
                typer.echo(f"scaling worker -> {n} ...")
                _scale_workers(n, settle_s)
            for trial in range(1, trials + 1):
                if dry_run:
                    rows.append(_dry_row(package, n, trial, floor))
                    typer.echo(f"  [dry] w={n} t={trial}")
                    continue
                typer.echo(f"  running w={n} t={trial} ...")
                row = _run_trial(base, package, n, trial, floor, timeout_s)
                rows.append(row)
                typer.echo(
                    f"    exec={row['exec_wall_clock_s']}s "
                    f"total={row['total_wall_clock_s']}s cost=${row['cost_usd']:.4f}"
                )
            if not dry_run:  # quiesce the prior count's containers before the next measurement
                _scale_workers(1, settle_s=0.0)
    finally:
        pd.DataFrame(rows, columns=_BENCH_COLUMNS).to_csv(out, index=False)
        typer.secho(f"wrote {len(rows)} row(s) -> {out}", fg=typer.colors.GREEN)


@app.command(name="critical-path")
def critical_path(package: Path = typer.Argument(..., exists=True)) -> None:
    """Print both DAG floors. The content floor sums spec.duration_s along the
    longest dependency chain; the render-time floor (Graph B) weights that same
    chain by mock provider latency -- the wall-clock no parallelism can beat.

    One shared implementation (scheduler.dag.Dag) computes both, so the CLI, the
    scheduler, and the notebook never drift."""
    from schema import ProductionPackage

    from scheduler.dag import Dag

    pkg = ProductionPackage.model_validate_json(package.read_text())
    dag = Dag(pkg)
    content = dag.critical_path_estimate()
    render = dag.critical_path_estimate(weight=_latency_weight)
    typer.echo(f"content critical path:    {content:6.1f}s  (spec.duration_s)")
    typer.echo(f"render-time floor (mock): {render:6.1f}s  (latency-weighted; Graph B)")


if __name__ == "__main__":
    app()
