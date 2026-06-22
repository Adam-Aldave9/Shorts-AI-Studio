# Build context is the repo root (see docker-compose.yml).
# ffmpeg is required at runtime for the final render.
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY libs/schema /app/libs/schema
COPY libs/storage /app/libs/storage
COPY libs/state /app/libs/state
COPY compositor /app/compositor

RUN pip install ./libs/schema ./libs/storage ./libs/state ./compositor

# Single instance (concurrency 1): the terminal node of the DAG.
CMD ["celery", "-A", "compositor.celery_app", "worker", "--loglevel=info", "--queues=composite", "--concurrency=1"]
