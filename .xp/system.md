# System Context

**Product**: Divine Ruin: The Sundered Veil — an audio-first AI tabletop RPG.
Players speak to an AI Dungeon Master over voice; there is no text chat and no
map. The screen is a glanceable, smartwatch-level HUD. Full RPG: voice character
creation, phase-based combat, companions, gods, crafting, multiplayer. The DM
narrates, voices every NPC, enforces the rules, and runs a persistent world.
Setting: a god (Veythar) broke the world trying to save it, creating the Veil,
the Sundering, and the Hollow corruption. Greyvale is the MVP region.

**Stack**: Two languages, one database — no code crosses the boundary, only
PostgreSQL + Valkey. Python 3.11+ (uv; asyncpg, redis.asyncio, all-async, typed)
runs the DM agent on LiveKit AgentSession: Deepgram STT → Claude → Inworld TTS,
plus an async worker. Everything else is TypeScript on Bun (never Node): Bun.serve
REST API, Expo/expo-router mobile client, Bun-SSR web. Bun-native APIs only
(Bun.serve / Bun.sql / Bun.redis / Bun.file), `bun`/`bunx`, never npx.
Tests: `bun test` (bun:test) for TS, `pytest` + `pytest-asyncio` for Python.
Whole fast lane: `bun run test:all`. Python fast lane alone: `bun run test:python`
(parallel `-n 8`) — never a bare serial `uv run pytest`.

**Surfaces & acceptance**: five surfaces, each with a harness that drives it at
its boundary.

| Surface | What presents it | Harness |
|---|---|---|
| Browser | `apps/web` Bun-SSR React app | Playwright — `e2e/specs/web-*.e2e.ts` |
| Automation | Expo/React Native mobile app | Maestro — `apps/mobile/.maestro/` flows + `scripts/maestro-acceptance.ts` |
| HTTP/WebSocket | `apps/server` Bun.serve REST; LiveKit token + data-channel endpoints | bun:test server suites |
| Message-event | Valkey/Redis `async_worker.py` polling loop | pytest — `test_ops_async_reset_runbook.py` |
| CLI | `agent.py dev`, `async_worker.py` LiveKit process entry points | pytest |

A story's ACs must be executed by the surface-driving test named in its Verify.
The real-LLM acceptance lane is deliberately excluded from `test:all` (ADR 0003,
API cost) and runs at pre-push and sprint close only.

**Layout**:
- `apps/agent` — Python DM agent: LiveKit voice agents, `@function_tool` toolset,
  `rules_engine.py` (pure deterministic math, zero IO, no LLM), `async_worker.py`
- `apps/server/src` — Bun/TS REST API: auth, character, activities, LiveKit
  tokens, image-gen, push, email
- `apps/mobile/src` — Expo client: HUD screens, zustand stores, LiveKit voice
- `packages/shared/src/entities` — shared TS entity types/schemas
- `content/` — JSON entity files seeded into the DB (SSOT for game content)
- `docs/` — canonical design docs; **start at `docs/INDEX.md`**, the section-mapped
  catalog. Never read a whole design doc; jump to the line range.
- `docs/milestones/` — per-phase milestone docs with AC checkboxes; `README.md`
  carries the phase status table and dependency graph
- `docs/decisions/` — ADRs. 0003 acceptance cost, 0004 tool scaling, 0007 verb/stage/resolve
- `e2e/specs` — Playwright specs; `scripts/` — `migrate.ts`, `seed_content.py`

**Conventions**:
- Python only in `apps/agent`; everything else Bun/TS. State is shared through
  the DB and Valkey, never through shared code.
- **Deterministic mechanics.** The rules engine is pure functions. The LLM decides
  *when* to invoke and *how to narrate* — never the math.
- **DB is the source of truth, not the prompt.** The agent re-queries every turn.
- **Audio first.** Every feature must work eyes-closed. Client displays
  server-pushed state only — no game logic, no maps, portraits, or text dialogue
  trees. (The Hollow intentionally violates the audio rules — wrongness by design.)
- Agent tools follow ADR 0007: a small fixed verb vocabulary with typed nouns as
  parameters. Consequences are tool-less Resolves; audio rides the location Stage.
  New content must not add tools — the strict-20-per-agent ceiling is ADR 0004.
  Adding, removing, or renaming a verb means grepping importers **and** the
  verb→agent registry assertions in the acceptance VERB_PRESENCE tables; those
  are not import-linked and only go red in the slow acceptance lane.
- New tools need docstrings — the LLM reads them to decide when to call.
- Third-party sources live under `apps/agent/.venv` and `node_modules`; open them
  BY PATH. Never search from `/` — scope every search to the repo and exclude the
  dependency trees. (sprint-046: a reviewer ran a whole-filesystem walk to find a
  file whose path it had already been given.)
- Ventriloquism: `[CHARACTER_NAME, emotion_hint]: "dialogue"`; untagged is the
  narrator. `CHARACTER_NAME` must be a registered key in `apps/agent/voices.py`
  (`VOICES`) — an unregistered tag silently falls back to `DM_NARRATOR`. An NPC's
  `voice_id` in `content/npcs.json` must equal a `VOICES` key.
- DB changes ship as migrations; `content/*.json` changes require a reseed, or
  strict loaders fail server startup.
- Content is written for the ear: short sentences, sound and smell before sight.
  Descriptions ≤3-4 sentences, NPC speech ≤1-3.
- Python files target ~300 lines, 500 hard cap; split by single responsibility.
- Run `ruff format` on changed Python before committing — pre-commit checks
  formatting (not `--fix`) and blocks.
- A story hands back a COMMIT that passed the commit hook, or a handback that
  names the failing hook and quotes its output. "Typechecks passed" with no
  commit is the false green constraint 1 forbids (sprint-046 story-010: pyright
  had 7 errors the report called green).
- Latency budget: 1500ms end-of-speech to first audio. Stream everything.
  Cost: cache system prompts; flag anything that raises token usage (`cost_model.md`).
- Branching: trunk is `main`. It is NOT PR-protected — verified 2026-09-04: classic
  protection is `enabled: false`, and the one active ruleset (`safety`, on the default
  branch) carries only `deletion` and `non_fast_forward`. A direct push to main
  succeeds. The branch discipline below is therefore a CONVENTION the xp release model
  enforces, not a wall the host enforces; don't cite "protected" as the reason for it.
  Work lands as first-parent merges of
  `paulingalls/sprint-*` / `story-*` / `free-*` branches. `.githooks/pre-push`
  runs the FULL acceptance gate (Docker/testcontainers) — allow ~10 minutes for
  any push or merge, or it is SIGTERM'd and fails silently. On a gate failure,
  read repo-root `flake-artifacts/` before calling anything a flake.

**Worktree bootstrap**: `bash scripts/init-worktree.sh`

**Worktree teardown**: `bash scripts/teardown-worktree.sh`
