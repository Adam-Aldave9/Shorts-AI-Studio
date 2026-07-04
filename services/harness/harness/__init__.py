"""Benchmark harness (spec §12.3). Not part of the runtime pipeline — a
short-lived CLI that replays the flagship package at worker counts 1, 2, 4, 8, 16
in mock mode and dumps the CSV feeding the throughput notebook."""
