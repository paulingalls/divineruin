FROM oven/bun:1.4.4 AS bun
FROM ghcr.io/astral-sh/uv:0.13.7 AS uv
FROM python:3.14.7-slim-bookworm
COPY --from=bun /usr/local/bin/bun /usr/local/bin/bun
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY scripts/pyproject.toml scripts/uv.lock ./scripts/
RUN uv sync --project scripts --frozen --no-dev --no-cache \
    && useradd --create-home --uid 10001 migrate
COPY scripts/migrate.ts scripts/seed_content.py ./scripts/
COPY scripts/migrations/ ./scripts/migrations/
COPY apps/agent/*.py ./apps/agent/
COPY content/ ./content/
ENV PYTHONUNBUFFERED=1
USER migrate
CMD ["sh", "-c", "bun --no-env-file run scripts/migrate.ts && exec scripts/.venv/bin/python scripts/seed_content.py"]
