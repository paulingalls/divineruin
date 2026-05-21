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
