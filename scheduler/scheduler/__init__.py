"""Scheduler service (spec §3, §6.1). The HTTP API and the DAG-walker daemon run
in the same process for v1; the boundary is clean if they ever need splitting."""
