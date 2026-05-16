# Sprint-001 Milestone Audit — Findings Index

Read-only audit of `docs/milestones/00_doc_updates.md` and `01_core_systems.md` against shipped code and current spec docs. Produced by sprint-001 stories 001–005; consolidated into the milestone files by story-006 (capstone).

Bias was toward unchecking when evidence was weak — Honesty over optimistic tracking.

## Findings files

| File | Scope | Confirmed | Aspirational | Unverified |
| --- | --- | --- | --- | --- |
| [phase-0.md](./phase-0.md) | M0.1–M0.4 doc updates (CLAUDE.md, INDEX.md, gp→gc, cross-refs) | 18 | 4 | 1 |
| [phase-1-rules-engine.md](./phase-1-rules-engine.md) | M1.1 d20 resolution + M1.2 skill tiers | 14 | 0 | 0 |
| [phase-1-characters.md](./phase-1-characters.md) | M1.3 resource pools (incl. 18 archetypes) + M1.4 leveling | 30 | 1 | 2 |
| [phase-1-async.md](./phase-1-async.md) | M1.5 async training + M1.6 companion errands | 11 | 5 | 0 |
| [dependency-versions.md](./dependency-versions.md) | Companion audit: Python, Bun/TS, Expo/RN pinned vs upstream | informational | — | — |

`dependency-versions.md` is informational — not consumed by the capstone; surfaces upgrade recommendations (now / next-sprint / hold) for separate planning.

## Material gaps surfaced (capstone annotations)

These were unchecked in `00_doc_updates.md` / `01_core_systems.md` with `<!-- see audit/<file> -->` pointers:

**Phase 0 documentation**
- `game_mechanics_magic.md:423,432` retains `gp` references (Revivify/Resurrection diamond components, explicitly named M0.3 targets); `economy/game_mechanics_p2p_trade.md:160` has a third instance.
- `INDEX.md` line ranges for `game_mechanics_archetypes.md` are off by ~133 lines (file is 1357 lines, INDEX claims 1224).
- `game_mechanics/` docs are not listed in CLAUDE.md's Knowledge System section — reachable only transitively via `INDEX.md`.
- M0.4 "no existing content deleted" cannot be verified positively without a pre-M0.4 baseline.

**Phase 1 leveling (M1.4)**
- Specialization fork: only L5 carries `specialization_fork=True`; L4 emits `elective_techniques` milestone but is NOT flagged as a fork. Spec wording says "L4/L5".
- "Unified" progression table covers attribute points + milestones + proficiency + fork in `leveling.py:LEVEL_PROGRESSION`, but HP gain lives separately in `hp_scaling.py:ARCHETYPE_HP_CONFIG`. Acceptance text names HP as a unified-table field.
- No standalone `apply_level_up(character_id)` agent tool. Level-up is folded into `award_xp` via `check_level_up` + `LEVEL_UP` event; AC narration is satisfied; the named tool deliverable is aspirational.
- No standalone `calculate_level(total_xp)` function; available via `check_level_up(0, total_xp, 1)` workaround (untested).
- 18 archetypes encoded in `apps/agent/rules_engine.py` + `hp_scaling.py`, not in `content/archetypes/` (no such directory).

**Phase 1 async (M1.5/M1.6)**
- Companion errand duration ranges: ALL 4 diverge from spec (scout 2–4 vs 4–8 hr; social 1–3 vs 3–6; acquire 2–4 vs 4–10; relationship 3–6 vs 2–4).
- Risk distribution table partial: only `scout` populated at full spec values; `acquire` reduced; `social`/`relationship` always 0/0; several danger×errand combos blocked at validation.
- **Artificer slot exception is dead code:** `validateSlotAvailability` accepts `archetype` + `hasPortableLab` params and is unit-tested, but both call sites in `activities.ts` pass neither. A live Artificer with a Portable Lab cannot benefit from the exception.
- 4 agent-tool deliverables missing as `@function_tool`s — HTTP-only paths: `initiate_training_cycle`, `resolve_training_midpoint`, `dispatch_companion_errand`, `resolve_companion_errand`.
- `training_activities` schema flattens spec's typed columns into `data JSONB` (behavioral fields present in payload).
- Client training "panel" is delivered as Catch-Up feed integration, not a stand-alone screen.

## Sprint-002 follow-up candidates

- Resolve surviving `gp` references in `game_mechanics_magic.md` (M0.3 cleanup) and update `INDEX.md` line ranges for archetypes.
- Decide M1.4 spec vs code: either rename the fork to L5-only and split HP from the unified table, or update code to match (add `specialization_fork` to L4, fold HP into `LEVEL_PROGRESSION`).
- Decide M1.6 spec vs code: either reduce duration spec to match shipped values, OR widen the shipped risk table to cover all 4 errand types at all danger levels.
- Fix the Artificer slot dead code: pass `archetype` + `hasPortableLab` from `activities.ts` call sites OR remove the unused validator params.
- Add the 4 missing agent tools, OR formally remove them from the deliverable list.
- Add a test for the `calculate_level(0, total_xp, 1)` workaround pattern (or expose a proper `calculate_level` helper).
- Capture the `apps/agent/check_tools.py` ↔ `apps/agent/async_worker.py` structural duplication (debt 5955c65a8cb3) — extract one shared `apply_skill_use_with_persistence` helper so the M1.2 hybrid-counter contract is enforced by construction rather than by integration test.

## Method

Per execution_plan.json §Milestone 1: for items with action verbs (add/implement/create), grep for the named symbol or file in `apps/agent/`, `apps/server/`, `packages/shared/src/entities/`, `content/`. For doc items, confirm the referenced doc/section exists and reflects the change. Output: table with item → evidence → status (confirmed / aspirational / unverified).
