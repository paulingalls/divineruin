FROM oven/bun:1.4.4 AS dependencies
WORKDIR /app
COPY package.json bun.lock ./
COPY apps/server/package.json apps/server/package.json
COPY apps/mobile/package.json apps/mobile/package.json
COPY apps/web/package.json apps/web/package.json
COPY packages/shared/package.json packages/shared/package.json
COPY packages/design-tokens/package.json packages/design-tokens/package.json
RUN bun install --production --frozen-lockfile --ignore-scripts --filter divineruin-server

FROM oven/bun:1.4.4 AS bun
FROM ghcr.io/astral-sh/uv:0.13.7 AS uv
FROM python:3.14.7-slim-bookworm
COPY --from=bun /usr/local/bin/bun /usr/local/bin/bun
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY --from=dependencies /app/node_modules ./node_modules
COPY --from=dependencies /app/packages/shared ./packages/shared
COPY packages/shared/src/ ./packages/shared/src/
COPY scripts/pyproject.toml scripts/uv.lock ./scripts/
RUN uv sync --project scripts --frozen --no-dev --no-cache \
    && useradd --create-home --uid 10001 migrate
COPY scripts/migrate.ts scripts/seed_content.py scripts/seed_catalogs.py scripts/seed_catalogs.ts ./scripts/
COPY apps/server/src/ ./apps/server/src/
COPY scripts/migrations/ ./scripts/migrations/
COPY apps/agent/*.py ./apps/agent/
COPY content/ ./content/
ENV PYTHONUNBUFFERED=1
USER migrate
CMD ["sh", "-c", "bun --no-env-file run scripts/migrate.ts && exec scripts/.venv/bin/python scripts/seed_content.py"]
