# System Context

**Product**: Divine Ruin: The Sundered Veil — an audio-first AI tabletop RPG.
Players speak to an AI Dungeon Master over voice; there is no text chat and no
map. The screen is a glanceable, smartwatch-level HUD. Full RPG: voice character
creation, phase-based combat, companions, gods, crafting, multiplayer. The DM
narrates, voices every NPC, enforces the rules, and runs a persistent world.
Setting: a god (Veythar) broke the world trying to save it, creating the Veil,
the Sundering, and the Hollow corruption. Greyvale is the MVP region.

**Stack**: Two languages, one database — no code crosses the boundary, only
PostgreSQL + Valkey. Python 3.14.7 (uv; asyncpg, redis.asyncio, all-async, typed)
runs the DM agent on LiveKit AgentSession: Deepgram STT → GPT-6 Luna → Inworld TTS,
plus an async worker. Everything else is TypeScript on Bun (never Node): Bun.serve
REST API, Expo/expo-router mobile client, Bun-SSR web. Bun-native APIs only
(Bun.serve / Bun.sql / Bun.redis / Bun.file), `bun`/`bunx`, never npx.
Tests: `bun test` (bun:test) for TS, `pytest` + `pytest-asyncio` for Python.
Commit fast tier: `bash scripts/test-fast.sh` checks staged language files.
Story Verify runs the card’s focused behavioral checks.
Story land retains `bun run test:all` before merge. PR CI owns full static
checks and Bun/Python non-acceptance suites. Sprint close owns deterministic
acceptance and Playwright; CI repeats them for free-patch coverage without
predecessor-result caching. Push scans outgoing secrets only.

**Check ownership and cost (story-157, 2026-10-13).** Recorded local code tree:
`7e88d33f0bfa9181482693a9b02de6c4958af2b5` (`8929fcdf`). Seconds below
are real elapsed times on this macOS host with installed frozen graphs, cached
Docker images and running checkout-owned services. The host was contended by
other work; the baseline acceptance run overlapped commit/land measurements.
The authorized draft PR will supply the recorded merge tree and CI timings;
historical PR 605 is not a substitute. This table is an incomplete measurement record, not AC sign-off.

| Owning tier | Leaf check / setup | Measured seconds | Explicit repeat and reason |
|---|---|---:|---|
| Commit | Staged env refusal, partial-stage refusal, shell `bash -n`, dispatch | Included in 0.62 overhead | Refusals inspect the index/worktree; not runtime tests |
| Commit | Index gitleaks scan | 0.048 | Land scans its merge index, a different input |
| Commit | Staged ESLint | 1.845 | CI full-project ESLint is clean-machine validation |
| Commit | Affected root / mobile / server / web `tsc` | 0.897 / 2.649 / 1.121 / 0.801 | CI checks every project, including deps-less and bypassed commits |
| Commit | Staged Prettier | 0.189 | CI checks all supported files on a clean machine |
| Commit | Agent Ruff check / format | 0.128 / 0.034 | CI full-project clean-machine validation |
| Commit | Whole-agent pyright | 21.647 | CI clean-machine validation |
| Commit | Other Python Ruff check / format | 0.058 / 0.057 | No whole-repo Python lint lane; staged paths own it |
| Push | Outgoing-history gitleaks | Included in 0.08 hook | Index scans cover a different input; no services or test children |
| PR CI | Full root/mobile/server/web typechecks, ESLint, Prettier (`lint:ts`) | Pending CI | Commit's affected-project/staged checks provide early feedback |
| PR CI | e2e `tsc`, ESLint (`lint:e2e`) | Pending CI | First typecheck for e2e; commit does not install its graph |
| PR CI | Full agent Ruff check, format, pyright (`lint-python`) | Pending CI | Commit repeats for early local feedback |
| PR CI | Scripts (`bun --env-file=.env test ./scripts`) | 0.033 at land | Human-required land fast lane; CI covers free patches |
| PR CI | Shared / design tokens | 0.499 / 0.012 at land | Human-required land fast lane; CI covers free patches |
| PR CI | Server bulk | 0.499 at land | Human-required land fast lane; isolated from real DB module |
| PR CI | Server DB / location / terrain / invite-store | 0.020 / 0.026 / 0.130 / 1.123 at land | Human-required land fast lane; preserve mock-isolation processes |
| PR CI | Mobile / web | 9.655 / 0.570 at land | Human-required land fast lane; CI covers free patches |
| PR CI | Python non-acceptance (`test:python`, eight workers) | 46.280 at land | Human-required land fast lane; CI covers free patches |
| Sprint close | Deterministic acceptance (`test:acceptance`) | 615.605 | CI is the only full acceptance for free patches; no predecessor cache |
| Sprint close | Playwright | 119.511 | CI covers free patches; no predecessor cache |
| Explicit approval | Paid acceptance / speech recognition | Not measured; approval empty | No automatic tier enables it |
| Setup | Root/e2e frozen Bun graphs, cached browser | 1.470 / 0.441 / 0.505 | Each isolated CI job installs its own required graph |
| Setup | Agent/scripts frozen uv graphs | 0.498 / 0.020 | Each isolated CI job installs its own required graph |
| Setup | Route generation, checkout authority and owned stack readiness | Included in fresh 14.50 total | CI generates mobile routes; separate job containers cannot share checkout ownership |
| Setup | Checkout migration / content seed | 0.472 / 0.844 | CI's isolated service jobs each migrate/seed; acceptance databases replay migrations for isolation |
| Setup | CI checkout/toolchain, service provisioning, ffmpeg/browser install, artifact upload | Pending CI | Different clean runners and job services; setup is included in job totals |

Tier totals: representative commit 30.09 s; actual implementation commit 19.72 s;
land 50.23 s; push 0.08 s; sprint 620.29 s. CI job totals remain pending:
lint-and-typecheck, lint-python, test-bun, test-python and test-e2e. The failed land
probe (58.50 s) is excluded: instrumentation required an environment variable
that a mobile test deliberately removes. The repaired probe is the successful
measurement. Child costs overlap and must not be summed into parallel tier totals.
Commit staged paths, index tree and skipped branches live in story DATA's
`evidence/representative-commit-input.json`; deletions are ignored by staged
language checks. The actual commit input is recorded separately. An empty-index
land scan is not a measurement of staged-language checks.

Fresh registered checkout setup: 14.50 s with cached images; warm setup: 8.67 s.
Ownership checks and teardown remain in `worktree-common.sh`. Focused acceptance
before/after: 64 passed in 63.53/21.05 s including startup; Postgres starts 9/1,
migration replays 9/7, full seed calls 9/7. Each mutating case still gets an
unseeded database; seed rollback and catalog mutation tests keep their own seed.
Read-only signature parameters use the session seed. Migration and seed costs
are retained to prove isolation and product seeding behavior.

The recorded-tree sprint run passed: 636 acceptance cases, 47 paid skips and
88 Playwright cases. Its JUnit results include all 64 card-focused cases
(seed_atomic 4, creature_catalog 4, catalog_encounter_cutover 56); those results
are reused, not rerun. Complete-lane startup counts before/after: Postgres 11/3,
migrations 9/7, seeds 9/7, LiveKit 1/0 (persistent reuse), checkout Compose 0/0
(already owned/running). Two Choir module session overrides retain their
mandatory-service prerequisite policy; they are session costs, not per-case
starts. The full baseline command used direct uv without the env-file dispatcher
and ended with two missing-REDIS_URL failures: 638.53 s, 634 passed, 47 skipped.
It supplies observed startup counts, not a successful tier measurement.
The sprint's separate E2E setup adds one Postgres and one Valkey start, a
0.372 s migration and 0.610 s seed dispatcher; those resources are torn down.
CI still needs a current-tree run to establish missing-env tolerance there
and split-Python duration against its 20-minute timeout. An ad-hoc Bun probe
confirmed a missing explicit env file is tolerated by the installed version.
Historical run 38164153205 checked out `5bed29d7`, tree
`e8c15ffb0df2b30530b49a61271ae6a24fec1a07`: jobs 69/54/75/1151/408 s
(lint-and-typecheck/lint-python/test-bun/test-python/test-e2e), a different tree.


Aliases `test`, `test:all`, `lint`, and workspace scripts expand to the leaf
checks above; they are dispatchers, not additional owners. Nonautomatic dev,
fix, maintenance, build and manually selected verification scripts are outside
these tiers; the complete package-script/CI-step inventory is in story DATA's
`evidence/inventory.json`. Product tests are retained; developer hook/runner
scaffolding is one-off evidence and never enters a regular test run. CI skips
documentation-only PRs. e2e type errors, deps-less commits and bypassed hooks
first receive full static validation at PR CI. The card records the human answer (2026-10-13): “Nightly tier — DROP it;
edit constraints 2 and 13 to remove the nightly tier (tiers: commit, story land,
push, sprint close, PR CI).” Constraints 2 and 13 match that decision.

**Surfaces & acceptance**: five surfaces, each with a harness that drives it at
its boundary.

| Surface | What presents it | Harness |
|---|---|---|
| Browser | `apps/web` Bun-SSR React app | Playwright — `e2e/specs/web-*.e2e.ts` |
| Automation | Expo/React Native mobile app | Maestro — `apps/mobile/.maestro/` flows + `scripts/maestro-acceptance.ts` |
| HTTP/WebSocket | `apps/server` Bun.serve REST; LiveKit token + data-channel endpoints | bun:test server suites |
| Message-event | Valkey/Redis `async_worker.py` polling loop | pytest — `test_ops_async_reset_runbook.py` |
| CLI | Product: `agent.py dev`, `async_worker.py`; developer: pre-commit, pre-merge-commit, pre-push, sprint, test-fast.sh, test-all.ts | Product pytest; developer entry points use disposable dispatch/failure scaffolding, recorded then removed (constraint 3) |

A story's ACs must be executed by the surface-driving test named in its Verify.
The real-LLM acceptance lane is deliberately excluded from `test:all` (ADR 0003,
API cost). Paid `real_llm`, `openai_real_llm` and `live_voice` lanes require
separate concrete per-run human approval; push or sprint-close is not approval.
Owned deterministic LLM/STT/TTS seams may prove command transport and mechanics
without certifying paid speech-recognition accuracy.

**Layout**:
- `apps/agent` — Python DM agent: LiveKit voice agents, OpenAI strict tool calls,
  `@function_tool` toolset,
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
- Python agents live in `apps/agent`; content seeding uses the separate `scripts`
  uv project. Other services use Bun/TS. State crosses languages through the DB
  and Valkey, never shared code.
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
- Client sound ids are content-registered aliases: `content/combat_sounds.json`
  and `content/action_sounds.json` map an id to a bundled stem, loaded by Python
  and `sound-registry.ts`. A card adding an id or a new publish site names
  `tests/acceptance/test_m22_audio_completeness_capstone.py` in Verify.
- Session start is shared by many suites: a card touching `session_hydration.py`,
  `participant_lifecycle.py` or `agent.py`'s session setup names
  `apps/agent/tests/session_lifecycle` in Verify. Those suites mock player rows,
  so a new DB call on the hydration path reds them (sprint-105: story-224's
  focused Verify was green while `test:python` had 5 reds).
- Checking a box in `docs/milestones/*.md` also moves the README phase count, the
  REMAINING.md position and `docs/INDEX.md` line ranges (`doc_index.py --write`);
  review checks all three; regenerate the index with `doc_index.py --write`.
- pytest collects only `test_*.py`. A pin module named otherwise (e.g.
  `creature_spec_pins_*.py`) may hold DATA a collected test imports, never test
  functions: sprint-062 story-130's pins ran only through its Verify, so no tier
  would have caught a later card breaking them.
- A sprint-header rule that a LATER card's walk enforces binds the card that
  AUTHORS the data too: name the check in that card's AC. Sprint-062: story-132
  authored three Hollow troops with one shared `vulnerable_to`; the header's
  pairwise-distinct rule surfaced only at story-133's plan review, after sign-off.
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
  scans outgoing secrets for every ref without starting services. Story land
  runs the fast lane before merge. PR CI owns static and non-acceptance checks;
  `.githooks/sprint` runs acceptance and Playwright at sprint close on the
  trial-merged integration tree. Free patches run the outgoing secret scan
  plus focused card Acceptance at the affected behavior/integration
  boundary on the trial-merged tree, then normal PR CI before merge. The lead
  adds broader free-patch acceptance only when the changed behavior warrants it;
  there is no automatic full local release suite for each free patch. Direct
  trunk pushes are not the release workflow. Do not repeat an identical broad
  suite on an unchanged tree during review without a concrete uncovered behavior. On a gate
  failure, read repo-root `flake-artifacts/` before calling anything a flake.

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
- **3, amended 2026-10-10.** Sprint 67's slate asked for a committed test of
  the land hook and of the Luna probe script; both would have run on every push.
  Human: tests of tests are fine while building them, not in the regular runs.
  Three meta-tests in the line-cap and strict-budget files were deleted (869e5222).
- **13 — wall clock.** Same day: story land gained the fast lane (~45 s) while
  acceptance stayed at sprint close, because land wall clock bounds the sprint.
  Human: efficient tests, harness and tiering keep wall clock down without
  lowering the bar.

**Handback contract** — what a story owes before it is handed back. Sprint 54
lost review rounds to both halves of this, five times.

- RUN THE CARD'S `Verify:` AND SAY YOU RAN IT. story-085 was handed back with a
  RED Verify (6 of 7 cases failing) and a tests-only diff — the production fix
  was never written, and nothing in the handback said so. A red Verify is the one
  state a story cannot be handed over in.
- RUN EVERY FOCUSED VERIFY THE CARD NAMES. Acceptance-related cards name a
  relevant acceptance test in Verify. Whole real-LLM acceptance runs at the
  comprehensive release gate.
- VERIFY THE AFFECTED CONSUMERS, NOT THE WHOLE REGRESSION SUITE. When a shape,
  field or event order changes, inventory its consumers and name focused checks
  in the card. Story tier is static; broad regression runs only in the full tier
  once at sprint close (human 2026-10-01). After a repair rerun affected checks;
  repeat mutations only when their guard or proof changed.
- Native XP CLI jobs do not wake the lead on completion. Keep the active turn,
  save each terminal session and log path, and poll handoff state, log age and
  child liveness about every 45 seconds. Inspect a stopped job's actual cause
  before choosing amend, direct review or resume; a stale marker alone is not
  evidence that the current job stopped.
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
or legacy labels fail closed without adoption or deletion during checkout teardown.
Back up and migrate or remove legacy data manually. CI service Postgres requires
the explicit GitHub Actions marker and cannot run Compose. Sweep inventories
Compose resources and acceptance-labeled containers, skips clearly foreign
owners, and deletes only consistently labeled stale checkouts from this clone.
Missing, mixed or unreadable ownership anywhere aborts before deletion; an empty
combined owned inventory or failed enumeration also refuses.
An unavailable registered worktree blocks sweep, including
locked worktrees on unmounted volumes. Remove or prune only registrations known
to be abandoned before sweeping their resources.
The sprint hook’s per-run Postgres and Valkey belong to the E2E lane.
Acceptance enters without those sibling-lane DSNs so its Python
lifecycle can validate checkout-owned settings; acceptance then loads the
checkout settings and provider credentials through its existing env file.
The sprint hook exports `ALLOW_PAID_TESTS=` and `REQUIRE_REAL_LLM=` empty in
all children; env files cannot restore approval. Acceptance unsets only the
sibling-lane `DATABASE_URL` and `REDIS_URL`.

**Dependency-changing landings**: before a land command that pushes automatically,
stage installs from the reviewed manifests/locks and refresh the integration
checkout's changed installed graphs; retain the old graph until push succeeds.
After merge, these commands install the committed graph:
`bun install --frozen-lockfile`, `bun install --cwd e2e --frozen-lockfile`,
`uv sync --project apps/agent --frozen`, `uv sync --project scripts --frozen`.
If land merges and then push fails, inspect HEAD and the close record before
retrying: the story worktree may already be removed. Never reformat with stale
tools to satisfy an upgraded lock.
Two clones ship to one origin (sprint-062): a land takes its base from the LOCAL
trunk branch but merges `origin/<trunk>`, so after the other clone releases run
`git fetch origin main:main` before landing, or land lists every file the other
release touched as unreviewed. After merging main into a sprint branch, run the
frozen installs above before pushing: the python lane's workspace-report test
reds on "installed package is missing". A story worktree cut before a
worktree-validator change tears down with its old scripts and fails; run
`bun run worktree:teardown --sweep` from the primary checkout afterwards.
