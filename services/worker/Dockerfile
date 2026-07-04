# Build context is the repo root (see docker-compose.yml).
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

COPY libs/schema /app/libs/schema
COPY libs/adapters /app/libs/adapters
COPY libs/rate-limiter /app/libs/rate-limiter
COPY libs/storage /app/libs/storage
COPY libs/state /app/libs/state
COPY services/worker /app/worker

RUN pip install ./libs/schema ./libs/adapters ./libs/rate-limiter ./libs/storage ./libs/state ./worker

# WORKER_CONCURRENCY is honored via the env var in docker-compose.
CMD ["sh", "-c", "celery -A worker.celery_app worker --loglevel=info --queues=render --concurrency=${WORKER_CONCURRENCY:-4}"]
