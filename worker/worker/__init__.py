"""Worker service (spec §6.3): the stateless, replicable unit. Pulls nodes,
acquires rate-limit tokens, calls providers (or mock mode), persists assets, and
reports cost. Scaled horizontally for the throughput experiments."""
