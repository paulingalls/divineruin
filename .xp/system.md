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
- Branching: trunk is `main`. It is NOT PR-protected — queried 2026-09-04:
  `branches/main/protection` 404s ("Branch not protected"), and the one active ruleset
  (`safety`, `~DEFAULT_BRANCH`) carries only `deletion` and `non_fast_forward`. No rule
  requires a PR or a status check, so a fast-forward push to main would go through.
  (`branches/main` still reports `protected: true` — that flag means "some ruleset
  applies", not "PR-gated"; don't read it as a wall.) The branch discipline below is a
  CONVENTION the xp release model enforces, not one the host enforces; don't cite
  "protected" as the reason for it. Work lands as first-parent merges of
  `paulingalls/sprint-*` / `story-*` / `free-*` branches. `.githooks/pre-push`
  runs the FULL acceptance gate (Docker/testcontainers) — allow ~10 minutes for
  any push or merge, or it is SIGTERM'd and fails silently. On a gate failure,
  read repo-root `flake-artifacts/` before calling anything a flake.

**A falsifier is a path into a moving tree, and nothing re-checks it until it
fires.** So it must run BEHAVIOUR — a test FILE or DIRECTORY, or a call — never
a grep of the fix site's text, and never a `-k` filter. A `-k` that matches
nothing exits 5, read as RED over healthy code: `3aea2529` at sprint-048's close,
and `1ffd99cf` at sprint-049's after story-030 renamed a test class. A text grep
reds the moment a correct fix moves the code: `b8b869ae` went red when story-029
put the payload in a builder. When a change MOVES or RENAMES a test file or
class, grep `work.md` for the old name and re-resolve every record pointing at it.

**Constraint case law** — the incident each `.xp/constraints.md` item was
written against. The rule is the wall; this is why it is where it is. Cite the
item number, not this section.

- **2 — file cap.** Two reviewers spent a round arguing about `content/*.json`
  before the human ruled authored data exempt (2026-09-04).
- **4 — tolerance.** Sprint-048's narration normalizer coerced the shapes I had
  seen and let its `else` absorb every shape I had not, so an errand "resolved"
  in silence.
- **5 — falsifiers.** Four red at the sprint-052 close: three grepped a name the
  fix had put elsewhere or in camelCase, one debt's polarity was inverted.
- **6 — producers.** Twice in sprint-045 we shipped a gate keyed on a token
  nothing produced: a reaction `window` the DM had to guess among 9.
- **7 — both sides.** Sprint-051 lost three land rounds to pins outside a card's
  directories. The acceptance clause is sprint-053's: a combat declaration or
  band card whose only lane is `test:all` ships untested against the harness.
- **8 — inventories.** Sprint-046 story-008 excluded four `companion_kael` sites
  without grepping; the reviewer found sixteen more on the session path.
- **9 — someone else's contract.** Sprint-047: a schema walk went green while
  the live API refused three agents, and a `MagicMock` invented every attribute
  production read (again in sprint-051). Sprint-048 added the PARSING side — we
  read the model's narration `segments` assuming dicts, and it sent a bare
  string. ADR 0004's strict ceilings are the gameplay agents' toolsets;
  narration's one tool was accepted strict the day we finally asked (sprint-050).
- **10 — code claims.** Sprint-048: four lead assertions taken from a
  DESCRIPTION were wrong, one stating `reactions_available`'s polarity backwards
  from its name. Sprint-053: five CARD claims were, including a `Verify:` naming
  a test file that does not exist — pytest exits 4 and nothing reds.
- **11 — recurrence.** The training midpoint judge red in sprints 48, 49 and 50,
  about 40% of pushes, each run shrugged off alone; the cause was the DM
  paraphrasing the resolved state away, one prompt line.
- **12 — absence and floors.** SPRINT 54 CAUGHT SEVEN VACUOUS GUARDS WITH THIS
  RULE, five of them inside cards written to fix a vacuous guard: 062's
  `half_on_success` check (deletable on either side, all 16 Python and 95 TS
  tests green, because every fixture row carrying the flag also carried damage);
  067's parity pin (mage and warrior of eighteen archetypes); 055's declarability
  pin (2 ability rows of 145); 081's parity walks (green with
  `content/spells.json` DELETED); 084's walk (the declare gate short-circuits and
  ACCEPTS what it cannot resolve, so for 11 spell-backed rows it ABSTAINED and
  the walk scored abstention as agreement); 088's armor gate (deletable — the one
  test reaching it with 0 damage equips no armor, so `_find_equipped` returns
  None and hides it); and 086, where tightening the ownership test DRAINED the
  neighbouring `p.type == "player"` check — deleting it left all 7127 Python
  tests green, though it redded at base. A floor must also be REACHABLE: a card
  refresh caught me writing one (`shorter than content/archetype_abilities.json`)
  that `query_info` can never meet, since it emits only the caller's
  class-and-level rows.
- **12, earlier.** Sprint-053's review: story-078's producer
  tripwire walked `archetype_abilities.json` only, so `content/spells.json` was
  walked by nothing; story-058's tripwire stayed green over an EMPTY corpus
  (`parents[4]` -> `parents[3]`); story-080's repo-wide line cap was vacuous
  against its own relocation, because `os.walk` over a missing directory yields
  nothing.

**Handback contract** — what a story owes before it is handed back. Sprint 54
lost review rounds to both halves of this, five times.

- RUN THE CARD'S `Verify:` AND SAY YOU RAN IT. story-085 was handed back with a
  RED Verify (6 of 7 cases failing) and a tests-only diff — the production fix
  was never written, and nothing in the handback said so. A red Verify is the one
  state a story cannot be handed over in.
- RUN EVERY LANE THE CARD NAMES. A card carrying a `THE SLOW LANE` line means
  `bun run test:acceptance:nollm` before finishing (constraint 7). Stories 073,
  083, 084, 085 and 088 all skipped it silently and a reviewer ran it each time —
  five for five, which means the gate was the review, not the executor.
- IF A COMMAND WILL NOT RUN, SAY WHICH AND WHY in the handback. A phantom red
  from the wrong command is worse than a missing run: story-087's handback
  claimed "infrastructure contamination" from 3 failures that `bun run
  test:server` excludes by design — the tree was green and the command was wrong.

**Checkout-owned local infrastructure**: `scripts/worktree-common.sh` is the one
authority used by bootstrap, Bun and Python test startup, and teardown. It hashes
the physical common Git directory for clone identity and the checkout Git
directory for checkout identity. Linked project names and default port offsets
include clone identity; the primary naming convention remains unchanged. A
validated `WT_PORT_OFFSET` may resolve a local collision, but never establishes
Docker ownership. `.env` is a request: its project and URL endpoints must match
the checkout before any reachability probe or Compose operation. Existing port
keys, when present, must agree; older primary files may derive absent port keys
from their coupled URLs without being rewritten. The Bun and Python adapters
also submit their actual runtime `DATABASE_URL` and `REDIS_URL` to this shared
authority. Port inspection errors and readiness ownership refusals fail
immediately. Compose resources carry clone and checkout labels. Resource
ownership permits metadata inspection and intentional teardown; connection
authority separately requires exactly one running checkout-owned service to
publish the selected loopback endpoint. A stopped owned volume is not proof of
the process listening on its former port. Missing, mixed, foreign, unreadable,
or legacy labels fail closed without adoption or deletion.
Back up and migrate or remove legacy data manually. CI service Postgres requires
the explicit GitHub Actions marker and cannot run Compose. Sweep deletes only
consistently labeled stale checkouts from the current clone and rejects empty or
unreadable enumeration.
The pre-push per-run Postgres and Valkey belong to the server and E2E lanes.
Acceptance and Python enter without those sibling-lane DSNs so their Python
lifecycle can validate checkout-owned settings; acceptance then loads the
checkout settings and provider credentials through its existing env file.

**Worktree teardown**: `bash scripts/teardown-worktree.sh`
