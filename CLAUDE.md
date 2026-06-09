# CLAUDE.md — Divine Ruin: The Sundered Veil

## Project

Audio-first AI tabletop RPG. Players speak to an AI Dungeon Master via voice — no text chat, no visual map. The screen is a glanceable HUD (smartwatch-level). Full RPG: character creation, combat, companions, gods, crafting, multiplayer. DM narrates, voices NPCs, enforces rules, runs a persistent world.

## Knowledge System

**Always start at `docs/INDEX.md`.** It is the canonical catalog of every design doc, grouped by category, with line-range section maps. Use it to find the right doc and jump to the relevant section — don't read whole files.

## Architecture

```
Expo Client (TS) ◄──► Bun/TS REST API ◄──► PostgreSQL + Valkey ◄──► Python DM Agent (LiveKit)
                  ◄──────── LiveKit voice + data channels ────────►
```

Two languages, one database. Python for DM agent (Anthropic plugin only exists for Python SDK). TypeScript/Bun for REST API and Expo client. PostgreSQL JSONB + Valkey (Redis-protocol) is the shared state layer.

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

No shared code between Python and TS. Shared data via PostgreSQL JSONB + Valkey.

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

**Ventriloquism:** One agent voices all characters. Tag format: `[CHARACTER_NAME, emotion_hint]: "dialogue"`. Untagged = narrator. `CHARACTER_NAME` must be a registered key in `apps/agent/voices.py` (`VOICES`, env-backed via `INWORLD_VOICE_*`) — unregistered tags silently fall back to `DM_NARRATOR`. NPC `voice_id` in `content/npcs.json` must equal a `VOICES` key. See `technical_architecture.md` — DM Agent Architecture section for tool pattern and details.

## External Docs

- **Inworld TTS** (voice provider): doc index at https://docs.inworld.ai/llms.txt — browse available voices, voice params (`speaking_rate`, `temperature`), and multilingual support. Pick voice names from the Inworld catalog when adding `INWORLD_VOICE_*` env vars.
- **LiveKit** (voice transport + agent SDK): use the `livekit-docs` MCP server (search/browse) — never rely on model memory for LiveKit APIs.

## Content Rules

Write for the ear: short sentences, concrete sensory details, sound/smell before sight. Descriptions ≤3-4 sentences. NPC speech ≤1-3 sentences. See `world_data_simulation.md` → Content Style Guide.

## Testing

**Bun:** `bun test` with `import { test, expect } from "bun:test"`
**Python:** `pytest` with `pytest-asyncio` for async tests
Rules engine must be exhaustively tested (pure functions, deterministic).

## Settled Decisions

Don't revisit: LiveKit, Python (agent), Bun (TS), Expo, PostgreSQL+JSONB, Valkey (Redis-protocol; `Bun.redis`/`redis.asyncio` clients + `REDIS_URL` keep their redis names), Deepgram Nova-3, Inworld TTS, Claude (LLM), zustand, expo-router, uv.

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
