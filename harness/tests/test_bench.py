"""bench CSV schema check (Phase 4 verification step 2).

A ``--dry-run`` sweep emits one row per (worker_count, trial) with the canonical
columns and the carried latency floor — exercising the schema with no docker fleet
or live scheduler. The real timing columns are filled by an actual run."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from harness.cli import _BENCH_COLUMNS, bench

FIXTURE = Path(__file__).resolve().parents[2] / "example-packages" / "rainforest-90s.json"


def test_bench_dry_run_csv_schema(tmp_path):
    out = tmp_path / "results.csv"
    bench(
        package=FIXTURE,
        workers="1,2",
        trials=2,
        out=out,
        scheduler_url=None,
        settle_s=0.0,
        timeout_s=1800.0,
        dry_run=True,
    )

    df = pd.read_csv(out)
    assert list(df.columns) == _BENCH_COLUMNS
    assert len(df) == 4  # 2 counts x 2 trials -> a row per trial
    assert sorted(df["worker_count"].unique().tolist()) == [1, 2]
    assert set(df["trial"]) == {1, 2}
    assert df["project_id"].tolist() == [
        "p_bench_w1_t1",
        "p_bench_w1_t2",
        "p_bench_w2_t1",
        "p_bench_w2_t2",
    ]
    # The latency-weighted floor (item 1) is carried into every row; n_nodes is the
    # flagship's 41 (10 ref + 30 shots + 1 voiceover).
    assert (df["critical_path_latency_s"] == 88.0).all()
    assert (df["n_nodes"] == 41).all()
