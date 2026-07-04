# Build context is the repo root (see docker-compose.yml).
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

COPY libs/schema /app/libs/schema
COPY libs/validator /app/libs/validator
COPY libs/rate-limiter /app/libs/rate-limiter
COPY libs/state /app/libs/state
COPY services/scheduler /app/scheduler

RUN pip install ./libs/schema ./libs/validator ./libs/rate-limiter ./libs/state ./scheduler

EXPOSE 8001
CMD ["uvicorn", "scheduler.main:app", "--host", "0.0.0.0", "--port", "8001"]
