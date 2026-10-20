# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install . && useradd --create-home --uid 10001 cmdb
COPY sample_data ./sample_data
COPY config ./config

USER cmdb
# Credentials are passed at runtime with --env-file; nothing secret is baked in.
ENTRYPOINT ["cmdb-health"]
CMD ["scan", "--cis", "sample_data/cis.json", "--relationships", "sample_data/relationships.json", "--as-of", "2026-10-01"]
