# Build context is the repo root (see docker-compose.yml) so shared libs can be
# copied in alongside this service.
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# Shared libraries first (better layer caching), then the service.
# afp-validator = the planning chain's terminal gate; afp-state = the Redis/Postgres
# write-through that persists the package for the scheduler to serve.
COPY libs/schema /app/libs/schema
COPY libs/validator /app/libs/validator
COPY libs/rate-limiter /app/libs/rate-limiter
COPY libs/state /app/libs/state
COPY libs/auth /app/libs/auth
COPY services/planning /app/planning

# Data the planning tier reads at runtime: the hand-authored mock package (MOCK /
# no-key fallback) and the world bible (real-run consistency). The package is
# installed into site-packages, so graph.py / world.py's parents[2] heuristic does
# NOT point at /app here — point the documented overrides at where we copy them.
COPY data/example-packages /app/example-packages
COPY data/world-bibles /app/world-bibles
ENV MOCK_PACKAGE_PATH=/app/example-packages/rainforest-90s.json \
    WORLD_BIBLE_PATH=/app/world-bibles/amazon-rainforest.json

RUN pip install ./libs/schema ./libs/validator ./libs/rate-limiter ./libs/state ./libs/auth ./planning

EXPOSE 8000
CMD ["uvicorn", "planning.main:app", "--host", "0.0.0.0", "--port", "8000"]
