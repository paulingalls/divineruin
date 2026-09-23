# ADR 0005 — Artificer training-slot exception deferred to Phase 5

Status: **Fulfilled** (original decision accepted 2026-05-21; Phase 5 implementation shipped)
Debt: `95de7fa141df` — discharged by Phase 5 slot accounting
Supersedes M1.6 wording: `01_core_systems.md` M1.6 AC4 (reworded as divergence)

## Decision (historical Phase-1 boundary)

Phase 5 has now shipped the Portable Lab item and recipe, slot accounting by the stored slot, and the crafting create path that checks class and lab ownership. The original Phase-1 deferral below explains why that work was not done earlier.


**The Artificer "craft on the Training slot with a Portable Lab" exception stays
unwired through Phase 1.** The crafting/training create paths in
`apps/server/src/activities.ts` keep calling
`validateSlotAvailability(slotCounts, activityType)` without `archetype` /
`hasPortableLab`. The validator's optional `archetype` / `hasPortableLab`
parameters (`slot_validation.ts` `validateSlotAvailability`) and their unit tests
(`slot_validation.test.ts`) remain in place as the **Phase-5-ready seam** — they
are intentionally not reachable from production yet.

M1.6's audit listed the unwired call sites as a dead-code "bug." It is instead a
deliberate deferral: the feature cannot be shipped cleanly in Phase 1.

## Context at acceptance (2026-05-21)

Two independent blockers, both verified against source:

1. **The Portable Lab is an unbuilt Phase-5 item.** Per
   `docs/game_mechanics/game_mechanics_crafting.md` L325 it is an Expert-tier
   *craftable recipe* granting Laboratory-tier workspace, and
   `docs/milestones/05_crafting.md` (M5.2/M5.4) owns it — explicitly NOT_SHIPPED in
   the Phase-5 audit. There is no item in `content/items.json`, no recipe in
   `activity_templates.ts:CRAFTING_RECIPES`, and no class-feature flag on
   `creation_classes.py:artificer`. So `hasPortableLab` has no real data source;
   wiring it now could only ever pass a hardcoded `false` — pure dead weight.

2. **Naive wiring would ship a slot-accounting over-capacity bug** (debt
   `95de7fa141df`). `countActiveBySlot` (`activities.ts:15-37`) buckets active work
   by `data->>'activity_type'`. A 2nd crafting placed on the Training slot via the
   exception is still stored as `activity_type='crafting'`, so the Training slot is
   never marked consumed. The Artificer could then *also* launch a Training activity
   → 2 crafting + 1 training + 1 errand = 4 concurrent, violating the spec's "max 2
   crafting + 1 errand for an Artificer" (`docs/game_mechanics/game_mechanics_core.md` L921).

## Options considered

1. **Wire it fully now** — load player class + portable-lab ownership, define the
   item, AND fix slot accounting. **Rejected**: pulls unbuilt Phase-5 crafting
   content + a non-trivial accounting change into a Phase-1 reconciliation sprint.
2. **Wire minimally** — pass the params, accept the over-capacity bug as debt.
   **Rejected**: knowingly ships a capacity bug to satisfy a checkbox.
3. **Accept divergence, defer to Phase 5** (chosen) — document why the call sites
   stay unwired, keep the validator seam + tests, and hand the work to Phase 5.

## Phase-5 requirements (fulfilled)

Tracked in `milestones/05_crafting.md` (M5.2 Artificer Portable Lab):

1. Add the Portable Lab item/recipe + the workspace-tier abstraction (M5.2/M5.4).
2. Fix `countActiveBySlot` so a crafting-on-training-slot **consumes** the Training
   slot — a later Training activity must then be rejected (debt `95de7fa141df`).
3. Wire `activities.ts` crafting create to load the player's class + portable-lab
   ownership and pass `archetype` + `hasPortableLab` to `validateSlotAvailability`.

## Consequences now

The Portable Lab item and recipe are shipped. `activity_create.ts` counts an
Artificer craft against its stored Training slot, and the crafting create path
checks the player's archetype and lab ownership before allowing that borrow.
`apps/agent/tests/acceptance/test_artificer_slot_e2e.py` verifies against the DB
that a borrowed slot blocks subsequent Training. The validator branch is reachable
from production; debt `95de7fa141df` is discharged.
