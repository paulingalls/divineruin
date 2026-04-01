# Divine Ruin — Game Mechanics Milestones

## Overview

These milestones define the deep game mechanics implementation, building on the existing voice pipeline, client app, and basic game systems already in the codebase. Each phase maps to one game mechanics design doc.

## Dependency Graph

```
Phase 0: Doc Updates ─────────────────────────────── (no deps, do first)
    │
Phase 1: Core Systems ──────────────────────────────── (foundation for all)
    │           │            │           │
    ▼           ▼            ▼           ▼
Phase 2:    Phase 5:     Phase 9:    Phase 6:
Archetypes  Crafting     Economy     NPCs
    │  ╲                              │
    ▼   ╲                             ▼
Phase 3:  ╲──────────► Phase 4: ◄── Phase 7:
Magic                   Combat      Bestiary
    │                      │
    ▼                      ▼
Phase 8:              (Integration)
Patrons
```

## Parallelism Guide

After Phase 1 completes, these groups can run in parallel:
- **Group A:** Phase 2 (Archetypes) → Phase 3 (Magic) → Phase 8 (Patrons)
- **Group B:** Phase 4 (Combat) → Phase 7 (Bestiary)
- **Group C:** Phase 5 (Crafting) — independent after Phase 1
- **Group D:** Phase 6 (NPCs) — independent after Phase 1
- **Group E:** Phase 9 (Economy) — independent after Phase 1

## Phase Files

| Phase | File | Source Doc | Milestones |
|---|---|---|---|
| 0 | [00_doc_updates.md](00_doc_updates.md) | `economy_reconciliation.md`, `game_mechanics_decisions.md` | 4 |
| 1 | [01_core_systems.md](01_core_systems.md) | `game_mechanics_core.md` | 6 |
| 2 | [02_archetypes.md](02_archetypes.md) | `game_mechanics_archetypes.md` | 5 |
| 3 | [03_magic.md](03_magic.md) | `game_mechanics_magic.md` | 4 |
| 4 | [04_combat.md](04_combat.md) | `game_mechanics_combat.md` | 6 |
| 5 | [05_crafting.md](05_crafting.md) | `game_mechanics_crafting.md` | 4 |
| 6 | [06_npcs.md](06_npcs.md) | `game_mechanics_npcs.md` | 4 |
| 7 | [07_bestiary.md](07_bestiary.md) | `game_mechanics_bestiary.md` | 4 |
| 8 | [08_patrons.md](08_patrons.md) | `game_mechanics_patrons.md` | 3 |
| 9 | [09_economy.md](09_economy.md) | `economy_reconciliation.md` | 3 |

**Total: 43 milestones across 10 phases**

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
