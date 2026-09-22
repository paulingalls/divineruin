# ADR 0003 — LLM acceptance run schedule and model

Status: **Accepted** (2026-05-20) — sprint-009 story-008
Concerns: `241b79ef3bbc`, `6e53a51c2cc0`

## Decision

**The Postgres-backed LLM acceptance scenarios run against the real Anthropic API
on a deliberate schedule — pre-sprint-close and during test authoring — not on
every PR. They use the production gameplay model (Haiku), gated by
`ANTHROPIC_API_KEY`, under a soft budget of ~$1 per sprint.**

## Context

story-008 built an acceptance harness (LiveKit test framework + testcontainers-
Postgres + pytest-bdd) so M1.5 acceptance criteria run against the *real* DM agent
instead of mocks (concerns `241b79ef3bbc` / `6e53a51c2cc0` deferred this out of the
story-005 capstone). Real-LLM tests cost money and are non-deterministic, so they
need an explicit run policy rather than firing on every commit.

## Schedule

- **Per-PR / pre-push lane:** LLM scenarios **skip cleanly** — the module is
  `skipif(not ANTHROPIC_API_KEY)`. The non-LLM infra test (`test_harness_db.py`)
  still runs under `REQUIRE_DOCKER` (it needs only Postgres), so the harness
  plumbing is exercised every push.
- **Pre-sprint-close and test authoring:** set `ANTHROPIC_API_KEY` and run
  `cd apps/agent && uv run pytest tests/acceptance/ -m acceptance` to validate the
  scenarios against real Haiku + Postgres. This is when the LLM cost is spent.

Gating on key presence (not a bespoke flag) keeps it simple: CI without the key
skips; a developer or the close step with the key runs.

## Cost budget

**Soft cap ~$1 per sprint.** M1.5 is 3 scenarios × (one agent turn on Haiku + one
judge call); well under the cap. As coverage grows across milestones, keep the
per-sprint acceptance run within this budget — if it would exceed, trim scenarios
or sample, and revisit this ADR.

## Model: Haiku, not Sonnet

The agent under test uses **`claude-haiku-4-5-20251001`** — the model the
production city/training gameplay agents actually use (`agent.py`). The original
story-008 AC said "real Sonnet"; that is **amended to Haiku** for production
parity, since the point of acceptance testing is to exercise the model players hit.
Testing on Sonnet would validate a model the gameplay path never runs. The judge
LLM is also Haiku (cheap, single provider). (sprint.json AC1 amended accordingly.)

## Consequences

- Acceptance scenarios are real integration tests — they have already caught bugs
  mocks could not (a JSONB-decode defect in `db_training._to_dict`, the
  25-strict-tools Anthropic 400 that drove story-011, and a stubbed-vs-real
  midpoint-decision mismatch).
- The per-PR lane stays fast and free; the real signal is collected on a cadence
  that matches its cost.
- Determinism: assert tool calls strictly; judge narration semantically with an
  LLM judge (tolerant of phrasing, strict on intent).

## Addendum (2026-09-20, Sprint 103) — production uses Luna

The production gameplay default is now `gpt-5.6-luna`, with reasoning disabled
and strict tool schemas enabled. The closed 27-case Luna matrix is the production
model acceptance surface. Existing Anthropic-backed acceptance scenarios remain
useful provider-specific integration checks and narration judges; they no longer
define production model parity. `GAMEPLAY_LLM=anthropic` is retained as an
explicit rollback route.

## Addendum (2026-09-22) — paid tests never run without human approval

Human decision: the pre-push hook had drifted to running every paid scenario on every push
(`REQUIRE_REAL_LLM=1`, story-019), and Sprint 103 added the 27-case Luna matrix to that lane.
Both directions of that drift are reversed and tightened past the original schedule: paid
tests (`real_llm`, `openai_real_llm`, `live_voice`) are skipped at collection everywhere —
pre-push, the sprint full tier, CI and ad-hoc runs — even when keys are present. They run
only case by case, when a human approves a specific run for a legitimate concern:
`ALLOW_PAID_TESTS=1 REQUIRE_REAL_LLM=1 uv run pytest <file>`. The hook strips both flags.
Enforced by `apps/agent/tests/_paid_tests.py` and `tests/test_paid_test_gate.py`, and at the
hook boundary by `scripts/test-prepush-environment.sh`.

## Addendum (2026-09-22) — GPT-6 Luna gameplay route

The default gameplay model is now `gpt-6-luna`, retaining reasoning effort none,
strict tool schemas, and the explicit `GAMEPLAY_LLM=anthropic` rollback. The cost
report uses the [GPT-6 Luna model page](https://developers.openai.com/api/docs/models/gpt-6-luna)
standard text rates retrieved 2026-09-22: $0.10 input, $0.01 cached input, and
$0.50 output per million tokens. The 2026-09-20 GPT-5.6 Luna evidence above
remains historical. The GPT-6 gather continuation and 27-case seeded matrix
await approval for paid execution; no gameplay-quality or latency improvement is
claimed yet.
