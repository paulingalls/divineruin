FROM oven/bun:1.4.4 AS dependencies
WORKDIR /app
COPY package.json bun.lock ./
COPY apps/server/package.json apps/server/package.json
COPY apps/mobile/package.json apps/mobile/package.json
COPY apps/web/package.json apps/web/package.json
COPY packages/shared/package.json packages/shared/package.json
COPY packages/design-tokens/package.json packages/design-tokens/package.json
RUN bun install --production --frozen-lockfile --ignore-scripts --filter divineruin-server

FROM oven/bun:1.4.4
WORKDIR /app
COPY --from=dependencies /app/node_modules ./node_modules
COPY --from=dependencies /app/apps/server ./apps/server
COPY --from=dependencies /app/packages/shared ./packages/shared
COPY apps/server/src ./apps/server/src
COPY packages/shared/src ./packages/shared/src
COPY packages/shared/package.json ./packages/shared/package.json
COPY content/loot_tables.json ./content/loot_tables.json
ENV NODE_ENV=production
WORKDIR /app/apps/server
USER bun
EXPOSE 3001
CMD ["bun", "run", "start"]
