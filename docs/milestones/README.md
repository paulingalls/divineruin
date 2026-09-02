# Divine Ruin — Game Mechanics Milestones

## Overview

These milestones define the deep game mechanics implementation, building on the existing voice pipeline, client app, and basic game systems already in the codebase. Each phase maps to one game mechanics design doc.

## Phase Completion Status

*Reflects delivery as of **sprint-044**, reconciled against the codebase by the
2026-09-01 audit pass (every flipped box carries an inline `<!-- verified -->`
evidence comment naming the file, symbol and RED-capable test). Per-milestone
detail lives in each phase doc; the remaining work is summarised in
[REMAINING.md](REMAINING.md).*

| Phase | Doc | Status | Delivered | Notes |
|---|---|---|---|---|
| 0 · Doc Updates | [00_doc_updates.md](00_doc_updates.md) | ✅ Delivered | 19/23 ACs | Doc-update backlog. M0.4 no-deletion discharged against baseline commit `f946ab6`. Residual: INDEX.md line-range drift has WIDENED to 2 docs. |
| 1 · Core Systems | [01_core_systems.md](01_core_systems.md) | ✅ **Complete** | 43/43 ACs | Core resolution/rules engine. The ADR-0005 Artificer training-slot deferral is DISCHARGED (Portable Lab shipped; debt `95de7fa141df` closed). |
| 2 · Archetypes | [02_archetypes.md](02_archetypes.md) | 🟡 Partial | 30/34 ACs | Re-verified still open. Combat tracks `reactions_available` but the phase loop never declares reactions (`combat_support.py:145` names the seam); no L20 capstone/legendary-companion unlock; no variant supplement-choice. |
| 3 · Magic | [03_magic.md](03_magic.md) | ✅ Delivered | 34/34 ACs | m31–m34 capstones (resonance, hollow-echo/wards, spell catalog, concentration/racial). **†Veil Ward** |
| 4 · Combat | [04_combat.md](04_combat.md) | ✅ Delivered | 65/65 ACs | m41–m46 capstones + M11–M20 extensions. **Caveat: 65/65 counts six authored sections — M4.7 and M4.8 shipped with ZERO authored ACs, so the count understates the phase.** Doc also names superseded tools and cites the deleted `wilderness_agent.py`. |
| 5 · Crafting | [05_crafting.md](05_crafting.md) | ✅ Delivered | 45/45 ACs | m52 workspace + m53 quality-pass capstones. Last residual closed sprint-045 story-005: trusted disposition rents free via `workspace.compute_workspace_rental_price` (story-011 moved it off the caller so the quote and the charge share one fn); `compute_rental_price` still returns 0.6x so repairs are unchanged. **†Veil Ward** |
| 6 · NPCs & Companions | [06_npcs.md](06_npcs.md) | ✅ Delivered | 30/34 ACs | m62/m64 capstones. All 4 residuals re-verified open and now quantified: no capital tier (4 tier rows), no name generator, Bard mentors = 0, Lira/Sable have 1 attack (spec ≥2). |
| 7 · Bestiary | [07_bestiary.md](07_bestiary.md) | ⬜ Not started | 1/41 ACs | Confirmed: no `creatures.json`, no creatures migration, no `validate_creature_stat_block`/`build_encounter`. Substrate is larger than the doc admits: `encounter_roles.py`, `encounter_loot.py`, `encounter_budget.py`, and **`encounter_templates.json` = 10 templates / 15 distinct stat blocks** (the doc still calls these "lore/prompts only"). `encounter.ts:1-10` names this refactor as pending. **Hazard: 3 incompatible tier/level tables.** |
| 8 · Patrons | [08_patrons.md](08_patrons.md) | ⬜ Not started | 0/34 ACs | Confirmed: all 10 gods have the 4 mechanical layers = `null`; narrative layers populated; full client leg already built. **Unblocked** (the doc's "Phase 3 blocks Layer 2" is stale). Doc also says roster is 4/10 — **it is 10/10**. Note: `test_patron_roster_consistency.py:131` ENFORCES the nulls per ADR 0001 and must be deleted when this phase builds. Hard *forward* dep on Phase 2. |
| 9 · Economy | [09_economy.md](09_economy.md) | 🟡 Partial | 5/80 ACs | Was under-counted. Byproducts found: workspace rental pricing (Phase 5), `player_reputation` read/write (M23), Location tier+personality (M6.2 — shipped as `settlement_tier`, a naming divergence M9.6 must reconcile). Integration sink; still blocks on Phase 7. |
| 10 · Terrain | [10_terrain.md](10_terrain.md) | ⬜ Not started | 0/17 ACs | Confirmed: no TerrainType enum anywhere in `apps/` or `packages/`; consumers remain terrain-blind. Smallest unstarted phase (3 milestones). **†Veil Ward** |
| 11 · World Loop | [11_world_loop.md](11_world_loop.md) | ⬜ Not started | 0/46 ACs | Confirmed: no world clock (`session_data.py:267 world_time` is the frozen constant `"evening"`), no tick worker, no cascade. **M23 did NOT land loop code** — it was design reconciliation. Layer-1 *consumption* is fully built; only the clock is missing. Tables `region_state`/`npc_state`/`world_events_log`/`god_agent_state`/`world_flags` migrated back in 001. **†Veil Ward** |
| 12 · Story Content | [12_story_content.md](12_story_content.md) | ⬜ Not started | 0/34 ACs | Planned. |

> **† Veil Ward full realization (M24, `execution_plan.json`).** The shipped Veil Ward is an interim per-player boolean; the customer-ratified full-spec ward is area/encounter-scoped, party-wide, duration-bound, multi-source (decision `veil-ward-scope-decision`). Scope split: **M24 owns** the pieces orphaned in the ✅-Delivered phases — Phase 3's per-source durations for the built Cleric/Druid/Paladin sources, and Phase 5's Artificer Veil Anchor recipe — plus the area/party scope-model core. **Phases 10 & 11 own** their pieces when built (Druid terrain gate; ambient/corruption/seasonal + Sacred-site world wards), building on M24. Tracked so the Delivered status doesn't hide the follow-on work. **M24 landed in sprint-040**
(migration `057_veil_ward_scope.sql`), so the scope-model core and the orphaned Phase 3/5
pieces are done; what remains under this dagger is only the Phase 10 and Phase 11 half.

## Dependency Graph

Primary spine (top-down):

```
    Phase 0: Doc Updates ──────────────────── (no deps, do first)
        │
        ▼
    Phase 1: Core Systems ─────────────────── (foundation for all)
        │           │            │
        ▼           ▼            ▼
    Phase 2:    Phase 5:     Phase 6:
    Archetypes  Crafting     NPCs
        │  ╲                     │
        ▼   ╲                    ▼
    Phase 3:  ╲              Phase 7:
    Magic      ╲             Bestiary
        │       ╲                │
        ▼        ▼               │
    Phase 8:  Phase 4:           │   (Phase 4 owns
    Patrons   Combat ──────────► │    game_mechanics_encounter_roles.md;
                 │                │    Phase 7 consumes role classifications)
                 ▼
                 Phase 9: Economy
                 (integration sink — fan-in from Phases 4/5/6/7
                  shown in cross-edges block below)
```

Cross-phase edges discovered during sprints 2-6 audits:

```
    Phase 4 → Phase 9   M9.4 loot/currency drops need M4.7 encounter_roles
                        (phase-encounter-roles.md, phase-9-economy.md)
    Phase 5 → Phase 9   workspace rental + commission/repair tiers depend
                        on Phase 5 crafting framework (phase-9-economy.md)
    Phase 6 → Phase 9   M6.1 role archetypes gate M9.6 merchant→pool
                        bindings; M6.3 mentor registry gates mentor fees
                        (phase-9-restock.md, phase-9-economy.md)
    Phase 7 → Phase 9   creature stat blocks + category tagging gate
                        material sell values (phase-9-economy.md)
    Phase 3 → Phase 8   Layer-2 Resonance modifiers in M8.1 need a
                        Resonance hook in Phase 3 magic.calculate_resonance
                        (phase-3-magic.md, phase-8-patrons.md)
    Phase 2 → Phase 6   M6.3 mentor training BLOCKS on Phase 2 M2.5
                        martial mentor system
                        (phase-2-archetypes.md, phase-6-mentors.md)
    Phase 4 → Phase 6   M6.4 companion combat profiles BLOCK on Phase 4
                        combat integration (phase-4-combat.md, phase-6-companions.md)
```

## Parallelism Guide

After Phase 1 completes. (Arrows within a group mean serial chain;
groups run in parallel with each other.)

- **Group A (Archetypes spine):** Phase 2 → Phase 3 → Phase 8
- **Group B (Encounter spine):** Phase 4 and Phase 7
  (both consume `game_mechanics_encounter_roles.md`; Phase 4 owns the doc, Phase 7 cross-refs — coordinate edits)
- **Group C (Independent leaf):** Phase 5 (Crafting) — no upstream blockers beyond Phase 1
- **Group D (NPCs spine):** Phase 6 — M6.1, M6.2 start after Phase 1; M6.3 mentor
  training BLOCKS on Phase 2 M2.5 (martial mentor system); M6.4 companion
  combat profiles BLOCK on Phase 4 (combat integration)

**Phase 9 (Economy) is the integration sink** — it can begin substrate
work after Phase 1, but key milestones BLOCK until upstream phases land:

- M9.4 loot/currency drops → requires Phase 4 (encounter_roles) + Phase 7 (creature roles)
- M9.x commission/workspace/repair pricing → requires Phase 5
- M9.6 merchant inventory pools → requires Phase 6 M6.1 role archetypes
- M9.x NPC service + mentor fees → requires Phase 6 M6.3 mentor registry

Plan Phase 9 work *last* in the integration window, not in parallel
with its upstream dependencies.

## Phase Files

| Phase | File | Source Doc | Milestones |
|---|---|---|---|
| 0 | [00_doc_updates.md](00_doc_updates.md) | `../game_mechanics/game_mechanics_economy.md`, `../game_mechanics/game_mechanics_decisions.md` | 4 |
| 1 | [01_core_systems.md](01_core_systems.md) | `../game_mechanics/game_mechanics_core.md` | 6 |
| 2 | [02_archetypes.md](02_archetypes.md) | `../game_mechanics/game_mechanics_archetypes.md` | 5 |
| 3 | [03_magic.md](03_magic.md) | `../game_mechanics/game_mechanics_magic.md` | 4 |
| 4 | [04_combat.md](04_combat.md) | `../game_mechanics/game_mechanics_combat.md`, `../game_mechanics/game_mechanics_encounter_roles.md` | 6 |
| 5 | [05_crafting.md](05_crafting.md) | `../game_mechanics/game_mechanics_crafting.md` | 4 |
| 6 | [06_npcs.md](06_npcs.md) | `../game_mechanics/game_mechanics_npcs.md` | 4 |
| 7 | [07_bestiary.md](07_bestiary.md) | `../game_mechanics/game_mechanics_bestiary.md`, `../game_mechanics/game_mechanics_encounter_roles.md` | 4 |
| 8 | [08_patrons.md](08_patrons.md) | `../game_mechanics/game_mechanics_patrons.md` | 3 |
| 9 | [09_economy.md](09_economy.md) | `../game_mechanics/game_mechanics_economy.md` + 6 subsystem docs in `../game_mechanics/economy/` (`supply_demand_engine.md`, `faction_reputation_pricing.md`, `merchant_inventory_restock.md`, `gold_sink_ledger.md`, `inflation_targets_controls.md`, `game_mechanics_p2p_trade.md`) | 10 |

**Total: 50 milestones across 10 phases**

## Audit Completion

These milestone docs reflect a full audit pass completed during
sprints 001–006 against the canonical `game_mechanics/` source docs
and the runtime codebase:

| Audit Sprint | Execution-plan M# | Scope |
|---|---|---|
| sprint-001 | M1 | Phases 0–1 (Doc Updates + Core Systems) — verify shipped coverage |
| sprint-002 | M2 | Group A: Phases 2 (Archetypes), 3 (Magic), 8 (Patrons) |
| sprint-003 | M3 | Group B: Phases 4 (Combat), 7 (Bestiary), integrate `encounter_roles.md` |
| sprint-004 | M4 | Phase 5 (Crafting) |
| sprint-005 | M5 | Phase 6 (NPCs) |
| sprint-006 | M6 | Phase 9 (Economy) — absorbed 6 subsystem docs |

Phase counts, source-doc paths, and the dep graph above were last
reconciled with the audit corpus during sprint-007 (M7). Per-phase
audit findings live in [`audit/`](audit/); the
[`audit/README.md`](audit/README.md) index also carries the
**Sprint-spec-cleanup punch list** — out-of-scope-but-real gaps that
don't fit any active milestone.

## Existing Infrastructure (Inputs)

These systems are already built and available as inputs for all milestones:

- **Agent Framework:** 8 LiveKit agents (Prologue, Creation, Onboarding, City, Wilderness, Dungeon, Combat, Base)
- **Rules Engine:** Basic dice rolls, skill checks, attacks, saving throws (`rules_engine.py`)
- **State Mutation:** Player movement, inventory, quest progress, XP, NPC disposition
- **Background Process:** Event bus, proactive companion speech, per-turn context injection
- **Client App:** Home screen, session screen, HUD overlays, pull-up panels, audio engine
- **Database:** PostgreSQL with JSONB entities, Redis caching
- **Content:** 50+ locations, NPCs, quests, items, scenes, encounters, factions, gods
- **Voice Pipeline:** STT (Deepgram), LLM (Claude), TTS (Inworld), ventriloquism
- **Async System:** Activity engine, catch-up layer, companion errands (basic)
- **Image Pipeline:** Generation, storage, serving, client caching

## Milestone Format

Each milestone follows this structure:
- **Goal:** What we're building and why
- **Inputs:** Dependencies from other milestones or existing codebase
- **Deliverables:** What code/data is produced
- **Acceptance criteria:** Testable checkboxes
- **Key references:** Sections of game mechanics docs to consult
