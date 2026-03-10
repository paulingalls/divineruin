# CLAUDE.md — Divine Ruin: The Sundered Veil

## Project

Audio-first AI tabletop RPG. Players speak to an AI Dungeon Master via voice — no text chat, no visual map. The screen is a glanceable HUD (smartwatch-level). Full RPG: character creation, combat, companions, gods, crafting, multiplayer. DM narrates, voices NPCs, enforces rules, runs a persistent world.

## Knowledge System

**Three tiers of progressive disclosure. Start with memory digests, drill into docs only when needed.**

### Tier 1 — Memory Digests (read these first)

Pre-extracted specs in `memory/` — compact, implementation-ready.

| Digest | Covers |
|---|---|
| `memory/game-mechanics.md` | d20 resolution, skills, combat phases, classes, status effects, death, economy, PvP |
| `memory/dm-agent-spec.md` | Three layers, tools, prompt architecture, ventriloquism, behavioral modes, affect system |
| `memory/world-simulation.md` | World clock, 4 sim layers, corruption formula, disposition decay, data layer |
| `memory/entity-schemas.md` | Location, NPC, item, quest, event, faction JSON schemas. Content tiers. |
| `memory/audio-pipeline.md` | Voice pipeline, 4 audio channels, ducking, ventriloquism, Hollow audio, music |
| `memory/client-ui-spec.md` | Expo screens, HUD layers, performance targets, brand tokens, art style |
| `memory/mvp-scope.md` | Scope boundaries, Greyvale arc, success criteria, milestone order |
| `memory/cost-constraints.md` | Session costs, margins, token estimates, optimization paths |
| `memory/lore-quick-ref.md` | Core mystery, 10 gods, races, cultures, Hollow taxonomy, geography |

### Tier 2 — Doc Section Index

`docs/INDEX.md` has line-range indexes for every doc. Use it to jump to specific sections.

### Tier 3 — Full Docs (docs/)

Read specific sections via INDEX.md, not whole files. For task-to-doc mapping, see `memory/doc-navigator.md`.

Key docs: `product_overview.md`, `game_design_doc.md` (1499 lines), `technical_architecture.md` (1499+ lines), `audio_design.md`, `world_data_simulation.md`, `mvp_spec.md`, `aethos_lore.md`, `cost_model.md`, `dev_milestones.md`, `player_resonance_system.md`, `brand_spec.md`, `image_prompt_library.md`

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

**Ventriloquism:** One agent voices all characters. Tag format: `[CHARACTER_NAME, emotion_hint]: "dialogue"`. Untagged = narrator. See `memory/dm-agent-spec.md` for tool pattern and details.

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

1. Read `dev_milestones.md` for current phase
2. Read milestone's referenced doc sections
3. Implement against acceptance criteria
4. Tests for every change (bun test / pytest)
5. DB changes need migrations
6. New tools need docstrings (LLM reads them to decide when to call)
7. **Update `docs/dev_milestones.md` checkboxes** when work is committed

## Environment Variables

See `.env.example`. Key vars: `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `ANTHROPIC_API_KEY`, `DEEPGRAM_API_KEY`, `INWORLD_API_KEY`, `DATABASE_URL`, `REDIS_URL`
