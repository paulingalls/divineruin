# CLAUDE.md — Divine Ruin: The Sundered Veil

## Project

Audio-first AI tabletop RPG. Players speak to an AI Dungeon Master via voice — no text chat, no visual map. The screen is a glanceable HUD (smartwatch-level). Full RPG: character creation, combat, companions, gods, crafting, multiplayer. DM narrates, voices NPCs, enforces rules, runs a persistent world.

## Design Docs (docs/)

**Read the relevant sections before writing code. These are specifications, not guidelines.**

| Document | File | Covers |
|---|---|---|
| Product Overview | `product_overview.md` | Vision, what and why. Read first. |
| Game Design | `game_design_doc.md` | All player-facing systems: combat, navigation, companions, classes, async, sessions, character creation. 21K words. |
| Tech Architecture | `technical_architecture.md` | Implementation blueprint: DM agent (3-layer), voice pipeline, tools, session lifecycle, multiplayer, testing, latency. |
| Audio Design | `audio_design.md` | Soundscapes, SFX, music, voice design, Hollow audio, UI sounds. AI generation prompts for all assets. |
| World Data | `world_data_simulation.md` | DB schemas, JSON entity formats, world sim rules, content style guide. |
| MVP Spec | `mvp_spec.md` | Scope, session-by-session arc, success criteria. Appendix has buildable JSON entities. |
| Lore Bible | `aethos_lore.md` | World history, gods, races, cultures, the Hollow, creature taxonomy. |
| Cost Model | `cost_model.md` | Per-session cost breakdowns, subscriber economics. |
| Dev Milestones | `dev_milestones.md` | Phased build plan with acceptance criteria. Feed to planning mode. |

## Architecture

```
Expo Client (TS) ◄──► Bun/TS REST API ◄──► PostgreSQL + Redis ◄──► Python DM Agent (LiveKit)
                  ◄──────── LiveKit voice + data channels ────────►
```

Two languages, one database. Python for DM agent (Anthropic plugin only exists for Python SDK). TypeScript/Bun for REST API and Expo client. PostgreSQL JSONB + Redis is the shared state layer. See `technical_architecture.md` → Language Architecture.

## Monorepo

```
divine-ruin/
├── docs/                   # Design docs (read-only reference)
├── apps/
│   ├── agent/              # Python — DM agent, background process, rules engine
│   │   ├── agent.py
│   │   └── pyproject.toml
│   ├── server/             # Bun/TS — REST API, auth, async, notifications
│   │   └── src/
│   │       ├── components/
│   │       └── lib/
│   └── mobile/             # Expo (TS) — mobile app
│       └── src/
│           ├── app/        # expo-router screens
│           ├── components/
│           ├── constants/
│           └── hooks/
├── packages/
│   └── shared/             # Shared TS package
├── package.json            # Workspace root
└── tsconfig.json
```

## Language Rules

### TypeScript / Bun (apps/server/, apps/mobile/, packages/shared/)

Use Bun exclusively — not Node.js.

- `bun <file>`, `bun test`, `bun install`, `bun run <script>`, `bunx <pkg>`
- Bun auto-loads `.env` — no dotenv

**Use Bun-native APIs:**
- `Bun.serve()` — not express
- `Bun.sql` — not pg/postgres.js
- `Bun.redis` — not ioredis
- `Bun.file` — not node:fs readFile/writeFile
- Built-in `WebSocket` — not ws

### Python (apps/agent/)

- Python 3.11+, `pyproject.toml`
- **uv** for all package management — not pip/poetry/conda
    - `uv sync`, `uv add <pkg>`, `uv run <cmd>`, `uv lock`
    - Docs: https://docs.astral.sh/uv/
- LiveKit plugins: `livekit-plugins-anthropic` (Claude), `livekit-plugins-deepgram` (STT), `livekit-plugins-inworld` (TTS), `livekit-plugins-silero` (VAD), `livekit-plugins-turn-detector`
- All async — use `asyncio`
- Type hints on all functions
- `asyncpg` for PostgreSQL, `redis.asyncio` for Redis

### Shared Data

No shared code between Python and TS. Shared data via PostgreSQL JSONB + Redis. Entity schemas in `packages/shared/` generate TS interfaces into `apps/server/src/generated/`. See `world_data_simulation.md` → Data Model.

## XP Values

All development follows the four values of Extreme Programming:

1. **Simplicity.** Do the simplest thing that works. Less code, fewer abstractions, shorter functions. If something feels complex, it probably needs to be broken down or rethought, not wrapped in more layers.

2. **Communication.** Code should read clearly without comments. Names, structure, and types convey intent. When something isn't obvious from the code itself, that's a design problem to fix — not a comment to write.

3. **Feedback.** Tests, logging, and error messages are first-class outputs. Write tests that confirm behavior and catch regressions. Log meaningfully. Surface errors with enough context to act on. Ship early and learn from real usage.

4. **Courage.** Do the right thing even when it's harder. Refactor code that works but reads poorly. Delete code that's no longer needed. Write the extra test. Challenge assumptions — including these docs — when something doesn't hold up.

## Golden Rules

1. **Audio first.** Every feature must work eyes-closed. Screen is supplementary. If it requires reading/tapping during a live session, redesign it.

2. **DM is the game.** Everything reaches the player through the DM's voice. Visual HUD elements supplement narration, never replace it.

3. **Deterministic mechanics.** Rules engine = pure functions, no LLM. Dice, damage, skill checks — always deterministic. LLM decides *when* to invoke and *how to narrate* results.

4. **State in the database.** DB is source of truth, not the prompt. DM agent queries DB every turn. If DB says NPC is dead, they're dead.

5. **Cost conscious.** Cache system prompts (90% savings). Haiku for routine, Sonnet for complex. Pre-generate async content in simulation ticks. Batch DB queries. See `cost_model.md`.

6. **Latency budget: 1500ms** end-of-speech to first audio. Stream everything. Don't wait for complete responses.

7. **Hollow breaks rules.** The Hollow intentionally violates audio mixing, spatial audio, and DM voice. This is by design — see `audio_design.md` → Sound of the Hollow.

## DM Agent — Three Layers

1. **Voice Agent:** LiveKit `Agent` subclass. Deepgram STT → Claude LLM → Inworld TTS. Real-time conversation.
2. **Background Process:** Async coroutine alongside voice agent. Monitors world events, updates warm prompt layer, injects proactive events.
3. **Toolset:** `@function_tool` functions in four categories: world queries (read), dice/mechanics (deterministic), state mutation (enforced rules), client effects (UI events).

**Ventriloquism:** One agent voices all characters. `tts_node` parses dialogue tags from LLM output, routes each segment to Inworld with the correct `voice_id`. See `technical_architecture.md` → Output Parsing.

## Tool Pattern

```python
@function_tool
async def query_location(context: RunContext, location_id: str) -> str:
    """Get location details: description, connections, NPCs, conditions."""
    session = context.userdata
    location = await db.get_location(location_id)
    location = apply_world_conditions(location, session.world_state)
    return json.dumps(location.to_narration_context())
```

- Return **data for LLM to narrate**, not pre-written narration
- Enforce game rules — LLM cannot bypass
- State mutations must write DB AND push data channel events to client
- One purpose per tool, compose for complex actions
- All DB access async

## Content Rules

Write for the ear: short sentences, concrete sensory details, sound/smell before sight. Descriptions ≤3-4 sentences. NPC speech ≤1-3 sentences. Sound cues explicit ("tankards clink against rough wood" not "the tavern is busy"). See `world_data_simulation.md` → Content Style Guide.

## Testing

**Bun:** `bun test` with `import { test, expect } from "bun:test"`
**Python:** `pytest` with `pytest-asyncio` for async tests

Rules engine must be exhaustively tested (pure functions, deterministic). DM behavior evaluated via semi-automated scenarios. See `technical_architecture.md` → Testing and Quality Strategy.

## Settled Decisions

Don't revisit: LiveKit (voice transport), Python (DM agent), Bun (TS runtime), Expo (mobile), PostgreSQL+JSONB (state), Redis (cache), Deepgram Nova-3 (STT), Inworld TTS (voices), Claude (narrative LLM), zustand (client state), expo-router (navigation), uv (Python packages).

## Don't

- Put game logic in the client — client displays server-pushed state only
- Let the LLM make mechanical decisions — LLM narrates, rules engine calculates
- Build visual-first features — no maps, no portraits, no text dialogue trees
- Ignore the cost model — flag anything that significantly increases token usage
- Skip the docs — if you're guessing, you haven't read the right section

## Dev Flow

1. Read `dev_milestones.md` for current phase
2. Read milestone's referenced doc sections
3. Implement against acceptance criteria
4. Tests for every change (bun test / pytest)
5. DB changes need migrations
6. New tools need docstrings (LLM reads them to decide when to call)

## Environment Variables

```
LIVEKIT_URL=
LIVEKIT_API_KEY=
LIVEKIT_API_SECRET=
ANTHROPIC_API_KEY=
DEEPGRAM_API_KEY=
INWORLD_API_KEY=
INWORLD_WORKSPACE_ID=
DATABASE_URL=postgresql://...
REDIS_URL=redis://...
```