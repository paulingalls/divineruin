# Divine Ruin — Game Mechanics Milestones

## Overview

These milestones define the deep game mechanics implementation, building on the existing voice pipeline, client app, and basic game systems already in the codebase. Each phase maps to one game mechanics design doc.

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
                 ▼   ▼   ▼   ▼
                 Phase 9: Economy
                 (integration sink — see cross-edges below)
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
```

## Parallelism Guide

After Phase 1 completes. (Arrows within a group mean serial chain;
groups run in parallel with each other.)

- **Group A (Archetypes spine):** Phase 2 → Phase 3 → Phase 8
- **Group B (Encounter spine):** Phase 4 + Phase 7
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
