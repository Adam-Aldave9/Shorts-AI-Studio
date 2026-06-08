# Build context is the repo root (see docker-compose.yml) so shared libs can be
# copied in alongside this service.
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# Shared libraries first (better layer caching), then the service.
COPY libs/schema /app/libs/schema
COPY planning /app/planning

RUN pip install ./libs/schema ./planning

EXPOSE 8000
CMD ["uvicorn", "planning.main:app", "--host", "0.0.0.0", "--port", "8000"]
