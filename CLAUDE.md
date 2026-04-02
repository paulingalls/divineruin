# CLAUDE.md — Divine Ruin: The Sundered Veil

## Project

Audio-first AI tabletop RPG. Players speak to an AI Dungeon Master via voice — no text chat, no visual map. The screen is a glanceable HUD (smartwatch-level). Full RPG: character creation, combat, companions, gods, crafting, multiplayer. DM narrates, voices NPCs, enforces rules, runs a persistent world.

## Knowledge System

**Two tiers. Use INDEX.md to navigate, read specific sections — not whole files.**

### Tier 1 — Doc Section Index

`docs/INDEX.md` has line-range indexes for every doc. Use it to jump to specific sections.

### Tier 2 — Full Docs (docs/)

Read specific sections via INDEX.md, not whole files.

| Category | Docs |
|---|---|
| **Game Mechanics** (canonical specs) | `game_mechanics/game_mechanics_core.md` (1103 lines), `game_mechanics/game_mechanics_combat.md` (1060), `game_mechanics/game_mechanics_archetypes.md` (1224), `game_mechanics/game_mechanics_magic.md` (542), `game_mechanics/game_mechanics_crafting.md` (587), `game_mechanics/game_mechanics_npcs.md` (885), `game_mechanics/game_mechanics_bestiary.md` (1234), `game_mechanics/game_mechanics_patrons.md` (366), `game_mechanics/game_mechanics_decisions.md` (186), `game_mechanics/economy_reconciliation.md` (250) |
| **Design & Architecture** | `product_overview.md` (254), `game_design_doc.md` (1514), `technical_architecture.md` (1732), `audio_design.md` (718), `world_data_simulation.md` (948), `player_resonance_system.md` (569) |
| **Content & Lore** | `mvp_spec.md` (968), `aethos_lore.md` (1750), `brand_spec.md` (249), `image_prompt_library.md` (379) |
| **Project** | `milestones/README.md` (10 phase files), `cost_model.md` (276), `agent_handoffs_and_scenes.md` |

## Architecture

```
Expo Client (TS) ◄──► Bun/TS REST API ◄──► PostgreSQL + Redis ◄──► Python DM Agent (LiveKit)
                  ◄──────── LiveKit voice + data channels ────────►
```

Two languages, one database. Python for DM agent (Anthropic plugin only exists for Python SDK). TypeScript/Bun for REST API and Expo client. PostgreSQL JSONB + Redis is the shared state layer.

## Monorepo

```
divine-ruin/
├── docs/                    # Design docs (read-only reference)
├── apps/
│   ├── agent/               # Python — DM agent, background process, rules engine
│   │   ├── tests/
│   │   └── pyproject.toml
│   ├── server/              # Bun/TS — REST API, auth, async, notifications
│   │   └── src/
│   ├── mobile/              # Expo (TS) — mobile app
│   │   └── src/
│   │       ├── app/         # expo-router screens
│   │       ├── components/
│   │       ├── hooks/
│   │       └── stores/      # zustand
│   └── audio/               # Audio assets (empty, future use)
├── packages/
│   └── shared/              # Shared TS types/schemas
│       └── src/entities/
├── content/                 # JSON entity files for DB seeding
└── docker-compose.yml
```

## Language Rules

### TypeScript / Bun (apps/server/, apps/mobile/, packages/shared/)

Use Bun exclusively — not Node.js. `bun <file>`, `bun test`, `bun install`, `bun run <script>`, `bunx <pkg>` (never `npx`). Bun auto-loads `.env`.

**Bun-native APIs only:** `Bun.serve()` (not express), `Bun.sql` (not pg), `Bun.redis` (not ioredis), `Bun.file` (not node:fs), built-in `WebSocket` (not ws).

### Python (apps/agent/)

Python 3.11+, `pyproject.toml`. **uv** for all package management (not pip/poetry/conda): `uv sync`, `uv add`, `uv run`, `uv lock`. All async with `asyncio`. Type hints on all functions. `asyncpg` for PostgreSQL, `redis.asyncio` for Redis.

LiveKit plugins: `livekit-plugins-anthropic`, `livekit-plugins-deepgram`, `livekit-plugins-inworld`, `livekit-plugins-silero`, `livekit-plugins-turn-detector`

### Shared Data

No shared code between Python and TS. Shared data via PostgreSQL JSONB + Redis.

## Development Values (Extreme Programming)

Apply XP values in all work:
- **Simplicity:** Minimum complexity for the current task. No speculative abstractions.
- **Communication:** Code should be self-evident. Tool docstrings, clear naming, no magic.
- **Feedback:** All tests must pass. Run the full suite. Fix warnings immediately.
- **Courage:** Fix problems when you see them — pre-existing or not. Refactor fearlessly.

## Golden Rules

1. **Audio first.** Every feature must work eyes-closed. If it requires reading/tapping during a live session, redesign it.
2. **DM is the game.** Everything reaches the player through the DM's voice. Visual HUD supplements, never replaces.
3. **Deterministic mechanics.** Rules engine = pure functions, no LLM. LLM decides *when* to invoke and *how to narrate*.
4. **State in the database.** DB is source of truth, not the prompt. DM agent queries DB every turn.
5. **Cost conscious.** Cache system prompts (90% savings). Haiku for routine, Sonnet for complex. See `cost_model.md`.
6. **Latency budget: 1500ms** end-of-speech to first audio. Stream everything.
7. **Hollow breaks rules.** Intentionally violates audio mixing, spatial audio, DM voice. By design.

## DM Agent — Three Layers

1. **Voice Agent:** LiveKit `AgentSession`. Deepgram STT → Claude LLM → Inworld TTS.
2. **Background Process:** Async coroutine. Monitors world events, updates warm prompt layer, injects proactive events.
3. **Toolset:** `@function_tool` functions — world queries (read), dice/mechanics (deterministic), state mutation (enforced rules), client effects (UI events).

**Ventriloquism:** One agent voices all characters. Tag format: `[CHARACTER_NAME, emotion_hint]: "dialogue"`. Untagged = narrator. See `technical_architecture.md` — DM Agent Architecture section for tool pattern and details.

## Content Rules

Write for the ear: short sentences, concrete sensory details, sound/smell before sight. Descriptions ≤3-4 sentences. NPC speech ≤1-3 sentences. See `world_data_simulation.md` → Content Style Guide.

## Testing

**Bun:** `bun test` with `import { test, expect } from "bun:test"`
**Python:** `pytest` with `pytest-asyncio` for async tests
Rules engine must be exhaustively tested (pure functions, deterministic).

## Settled Decisions

Don't revisit: LiveKit, Python (agent), Bun (TS), Expo, PostgreSQL+JSONB, Redis, Deepgram Nova-3, Inworld TTS, Claude (LLM), zustand, expo-router, uv.

## Don't

- Put game logic in the client — client displays server-pushed state only
- Let the LLM make mechanical decisions — LLM narrates, rules engine calculates
- Build visual-first features — no maps, no portraits, no text dialogue trees
- Ignore the cost model — flag anything that significantly increases token usage

## Dev Flow

1. Read `docs/milestones/README.md` for current phase
2. Read milestone's referenced doc sections
3. Implement against acceptance criteria
4. Tests for every change (bun test / pytest)
5. DB changes need migrations
6. New tools need docstrings (LLM reads them to decide when to call)
7. **Update milestone checkboxes in `docs/milestones/`** when work is committed

## Environment Variables

See `.env.example`. Key vars: `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `ANTHROPIC_API_KEY`, `DEEPGRAM_API_KEY`, `INWORLD_API_KEY`, `DATABASE_URL`, `REDIS_URL`
