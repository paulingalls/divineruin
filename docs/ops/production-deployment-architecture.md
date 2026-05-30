# Production Deployment Architecture

Status: **Decided** (2026-05-29). This is the canonical target for how Divine Ruin rolls out in production. Local infra (`docker-compose.yml`, `.env`, CI, e2e) is mapped to this target — see [Local → production mapping](#local--production-mapping).

## Summary

Divine Ruin deploys to **DigitalOcean, all-managed**: the two stateful backends (Postgres, Redis) and the voice transport (LiveKit) are **managed services**, not containers we operate. The two application processes — the Python DM agent and the Bun/TS REST API — deploy as **containers**. Binary assets live in **DigitalOcean Spaces** (see [Asset storage](#asset-storage)).

The guiding principle is the Golden Rule **cost-conscious, low-ops**: for an MVP with 10–15 testers, managed Postgres/Redis and LiveKit Cloud remove operational burden at a cost that the [cost model](../cost_model.md) absorbs. Self-hosting is a later optimization, not an MVP concern.

## Target architecture

```
        Mobile clients (Expo) ──WebRTC──► LiveKit Cloud ──► DM Agent container (Python)
                  │                                              │
                  └────────────HTTPS (REST)──► Server container (Bun/TS)
                                                   │             │
                              ┌────────────────────┴─────────────┴───────────┐
                              ▼                    ▼                          ▼
                     DO Managed Postgres   DO Managed Redis           DO Spaces (assets)
```

| Component | Production form | Hosting | Notes |
|---|---|---|---|
| Mobile client | Expo app (EAS build) | App Store / Play Store | Connects to LiveKit Cloud (voice) + the server (REST). |
| Voice transport | **LiveKit Cloud** (managed) | LiveKit Cloud | Room mgmt, SFU, agent dispatch. Self-hosted `livekit-server` is used **only** for local acceptance tests, never prod. |
| DM agent | **Container** (Python, LiveKit Agents SDK) | DO App Platform / droplet | Co-located background process. Scales with concurrent sessions. |
| REST API | **Container** (Bun/TS) | DO App Platform / droplet | Auth, async activities, push, settings. Stateless; horizontally scalable. |
| Postgres | **DO Managed Postgres** | DigitalOcean | Source of truth (JSONB entities + state). Daily backups + PITR via the managed offering. |
| Redis | **DO Managed Redis** | DigitalOcean | Session cache, voice registry, activity timers. |
| Binary assets | **DO Spaces** (S3-compatible) | DigitalOcean | Per the [object-storage migration](../ideas/object-storage-migration.md). |

## Local → production mapping

Local development mirrors this topology with **containerized stand-ins for the managed services** so no developer needs cloud credentials to work. Divine Ruin's local stack runs on **unique, project-dedicated ports** — Postgres `55432`, Redis `56379` — so it never collides with a shared host Postgres/Redis or other projects on the same machine. (story-017 reconciles `docker-compose.yml`, `.env.example`, CI, and e2e to these ports; the values below are the target this story delivers.)

| Concern | Local (dev) | Production |
|---|---|---|
| Postgres | `docker-compose` `divineruin-postgres` on `localhost:55432` | DO Managed Postgres (`DATABASE_URL` from the managed cluster) |
| Redis | `docker-compose` `divineruin-redis` on `localhost:56379` | DO Managed Redis (`REDIS_URL` from the managed cluster) |
| LiveKit | self-hosted `livekit-server` container (acceptance tests only) | LiveKit Cloud (`LIVEKIT_URL=wss://<project>.livekit.cloud`) |
| Agent / Server | `bun`/`uv run` on the host | containers on App Platform / droplet |
| Assets | rustfs container (per object-storage migration) | DO Spaces |
| Config | single root `.env` (Bun auto-loads; Python reads the same) | platform env/secrets (never a committed file) |

The only thing that changes between local and prod for the application code is **environment variables**. `apps/agent/db.py` and `apps/server/src/db.ts` read `DATABASE_URL` / `REDIS_URL` from the environment; the agent reads `LIVEKIT_*` in `apps/agent/agent.py`. Nothing hardcodes an endpoint, and there is no environment branching in app code.

## Environment & secrets

All runtime config flows through environment variables (see `.env.example` for the full list). In production these are **platform-managed secrets** (DO App Platform env vars / droplet secret store) — never a committed `.env`. The canonical required set: `DATABASE_URL`, `REDIS_URL`, `LIVEKIT_URL`/`LIVEKIT_API_KEY`/`LIVEKIT_API_SECRET`, `ANTHROPIC_API_KEY`, `DEEPGRAM_API_KEY`, `INWORLD_API_KEY`, `JWT_SECRET`, `INTERNAL_SECRET`, plus the Spaces `S3_*` trio once the asset migration lands.

The agent validates its required env eagerly at startup (`apps/agent/agent.py`); the server reads lazily per-request (`apps/server/src/db.ts`) so no-DB unit tests run without config. Both behaviors are correct for their context and need no change for production.

## Migrations & seed on deploy

- **Schema:** `bun run scripts/migrate.ts` runs against the managed Postgres `DATABASE_URL` as a deploy step (before the new container takes traffic).
- **Content seed:** `scripts/seed_content.py` loads `content/*.json` into the content tables. Strict loaders fail-loud on malformed content, so a bad seed fails the deploy rather than booting a half-populated DB.
- Both are idempotent against an already-migrated/seeded cluster.

## Asset storage

Binary media (location art, generated portraits, audio) is **not** part of this story's scope and is **not** restated here. The canonical plan is [`docs/ideas/object-storage-migration.md`](../ideas/object-storage-migration.md), which already specifies **DO Spaces for production** (rustfs container locally / in CI) and is consistent with this architecture. When that migration's execution plan lands, this doc's [target table](#target-architecture) row for assets is satisfied by it; until then, assets remain bundled/filesystem as today. This doc defers to that spec — it is the single source of truth for asset storage, not a competing statement.

## Contradictions this doc resolves

This document is the canonical deployment reference; where older docs disagree, this one wins:

1. **Cloud provider.** `technical_architecture.md` (Cloud Platform) previously recommended *AWS or GCP*. **Resolved: DigitalOcean** — cheaper and lower-ops for the MVP, and consistent with the asset plan already targeting DO Spaces. `technical_architecture.md` now points here.
2. **LiveKit hosting.** **Resolved: LiveKit Cloud (managed)** for production. Self-hosted `livekit-server` exists only for local acceptance tests.
3. **Cost model assumption (open follow-up).** `cost_model.md` computes its per-session numbers assuming **self-hosted LiveKit**. With LiveKit Cloud chosen, those figures need recomputing — tracked as debt, **not** done in this story.

## Open follow-ups

- Recompute `cost_model.md` for LiveKit Cloud participant-minute pricing (debt).
- Execution plan for the object-storage migration (DO Spaces) — separate story.
- Containerization artifacts (Dockerfiles for agent + server) are implied by "deploy as containers" but authored when the deploy pipeline is built — not in this doc's scope.
