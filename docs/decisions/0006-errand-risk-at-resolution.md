# ADR 0006 — Companion-errand risk rolled at resolution, not dispatch

Status: **Accepted** (2026-05-22) — sprint-010 story-007
Supersedes the "TS server is the sole authority for errand risk" framing in `errand_risk.ts`.
Resolves: concern `c34eb1f1875a` (cross-language risk re-roll drift).

## Decision

**The companion-errand injury roll happens in the Python `async_worker` at
resolution time, not in the TS server at dispatch time.** The risk roll lives in
exactly one place (`apps/agent/errand_risk.py`). Dispatch — on either entry point
(the TS REST handler, and the Python agent tool added in story-009) — performs
only the deterministic **blocked-combo + slot** validation; it rolls no risk and
stores no `risk_outcome`.

## Context

Previously `errand_risk.ts:rollErrandRisk()` rolled a d100 at dispatch
(`activities.ts`) and stored `risk_outcome` in the activity's JSONB params; the
Python worker only read and narrated it. Story-009 adds a second dispatch entry
point — a Python `@function_tool` — which cannot reach the TS server (the agent
shares state only via Postgres/Redis, never via HTTP to the API). That path would
have had to re-roll risk in Python, forking the risk logic across two languages.

Key observation: **nothing reads `risk_outcome` between dispatch and resolution.**
A grep across `apps/server`, `apps/mobile`, and `packages` found the only readers
are the worker (at resolution) and the narration template (also at resolution).
The player cannot observe the outcome until the errand resolves, so rolling at
dispatch vs. at resolution is behaviorally identical.

## Consequences

**Better**
- The risk roll + table exist once, in Python, co-located with their sole consumer
  (the worker). No cross-language duplication; story-009's agent dispatch needs no
  risk logic of its own.
- Resolution is the natural roll site; the worker freezes the rolled outcome in its
  cached outcome, so TTS retries don't re-roll.

**Watch**
- The danger-level → risk **spec** (`game_mechanics_core.md` §Companion Risk
  L887-892) is the oracle, but it is conformance-pinned by **two** hand-written
  tables: `apps/agent/errand_risk.py` (full risk table + blocked combos) and
  `apps/server/src/errand_risk.ts` (blocked combos only). A spec edit must update
  both language pins by hand.
- `numeric_to_danger` fails closed (raises) on an unknown `danger_level`; at
  resolution this surfaces as a logged error + retry rather than silently
  downgrading a dangerous destination.

## Alternatives rejected
- **Agent dispatch calls the TS REST API to roll** — violates the no-agent→server-HTTP
  architecture (state is shared only through the DB).
- **Port `rollErrandRisk` into Python dispatch too** — the duplication this ADR exists
  to avoid; would make the "single authority" claim false in a new way.
