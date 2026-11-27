# Divine Ruin — Game Mechanics Milestones

## Overview

These milestones define the deep game mechanics implementation, building on the existing voice pipeline, client app, and basic game systems already in the codebase. The phase files link to their design sources. Phase 14 records remaining execution and certification gaps, and Phase 15 records the authored-content gaps.

## Phase Completion Status

*Reconciled against the codebase on **2026-11-26**. Fractions count the phase-doc checkboxes. Status caveats and remaining-work evidence live in [REMAINING.md](REMAINING.md).*

| Phase | Doc | Status | Delivered | Notes |
|---|---|---|---|---|
| 0 · Doc Updates | [00_doc_updates.md](00_doc_updates.md) | ✅ Delivered | 22/23 ACs | One documentation criterion remains open; see [REMAINING.md](REMAINING.md). |
| 1 · Core Systems | [01_core_systems.md](01_core_systems.md) | 🟡 Partial | 43/44 ACs | Voice assignment of the standard array at creation is open; Artificer-slot evidence in [REMAINING.md](REMAINING.md). |
| 2 · Archetypes | [02_archetypes.md](02_archetypes.md) | ✅ **Complete** | 34/34 ACs | Complete recorded criteria; reaction mechanics and spoken-pause limits in [REMAINING.md](REMAINING.md). |
| 3 · Magic | [03_magic.md](03_magic.md) | 🟡 Partial | 34/34 ACs | [Spell ledger](03_spell_ledger.md) records 11 engine, 4 narrated, 72 unwired and 0 uncertified spells. **†Veil Ward** |
| 4 · Combat | [04_combat.md](04_combat.md) | ✅ Complete | 83/83 ACs | Retreat, opportunity attacks, all 16 martial combat electives, weapon equip proficiency, and the five Marshal orders (Direct Strike, Coordinated Assault, Sacrifice Play, Reposition, Field Medic Order) are exercised. Registered tools cover Quick Fingers item transfers, wary retaliation and Fate continuation. |
| 5 · Crafting | [05_crafting.md](05_crafting.md) | ✅ Delivered | 45/45 ACs | Complete recorded criteria. **†Veil Ward** |
| 6 · NPCs & Companions | [06_npcs.md](06_npcs.md) | ✅ **Complete** | 34/34 ACs | D-4/D-5 are recorded; M6.1 retains the lead’s “where applicable” reading. See [REMAINING.md](REMAINING.md). |
| 7 · Bestiary | [07_bestiary.md](07_bestiary.md) | 🟡 Partial | 43/43 ACs | Catalog, encounter cutover, guaranteed loot, party skill gates, exclusive recipe/trade disposition and Hollow loot taint exercised; generated entry/resume/victory, catalog summaries, party-fit template discovery and purification exercised; Knight boss rise/hold/reload and Veilrender field/regeneration/suppression/area actions exercised, both bosses reachable at Ashmark Front; Absorb Magic exercised; the Still's anchors, Rejection and zone charm exercised; the Architect's walls, Reshape, Entomb, Cathedral, constructs and legendary actions exercised; Hollowed hallucinations, Wisdom drain and Greater Restoration exercised; equipped magical weapons and Infuse Item bypass the Knight’s physical resistance. Seeded Choir fights exercise its whole kit, core victory and settlement, and both own-turn silence exposures. Native Choir audio certification is tracked in [M14.1](14_engine_completeness.md#milestone-141--narrated-only-mechanics-and-voice-certification). |
| 8 · Patrons | [08_patrons.md](08_patrons.md) | 🟡 Partial | 33/34 ACs | M8.1 Layers 1–3, all ten Layer 1 gifts, all Layer 2 Resonance effects, the Unbound Path and gods.json validation ship; 20-minute deed-journal judgment ships through real-session coverage; M8.2 recharge, availability and the native character sheet ship; M8.3 ships the 180-pair Layer 4 lookup and 103 active engine clauses alongside 85 active narrated clauses. 12 engine clauses remain pending. Aelora’s Common Bond gives artificers, bards and diplomats +1 on live Crafting checks, recipe experiments and queued crafting rolls. Aelora’s Restoring Guard returns up to 2 Stamina after a guardian’s Intercept moves damage or a warden’s Bark Skin applies. Aelora now grants +1 Insight for household omens (stacking with Hearthkeeper’s Bond) and +1 Persuasion for commerce. Thyra now grants +1 Religion for sacred groves and +1 Nature for seasonal omens. Aelora’s fence prices remain pending. Nythera grants +1 for coastal shelter, peaceful port passage and vessel repair during a journey. Orenthel grants +1 for sanctuary equipment repair, restoring a blighted grove and negotiating care for wounded enemies. Veythar’s paladins gain +1 Religion for ancient oaths and his oracles gain +1 Arcana for remembered visions. Veythar’s Hidden Knowledge gives rogues and spies +1 on Investigation discovery rolls, including Still illusions and Lorekeeper’s Insight discovery rerolls. Skill-mode Investigation uses its usual modifier. Kaelen’s clerics gain +1 Religion for fallen soldiers’ rites and his oracles gain +1 History for martial omens. Syrath’s clerics gain +1 Religion for concealed devotional symbols and paladins gain +1 History for oaths whose patron’s name was erased. Mortaen’s diplomats gain +1 Persuasion on skill and social checks to negotiate the return of a body for burial. Zhael’s artificers gain +1 to any skill check to repair clocks or timing mechanisms, and seekers gain +1 Investigation to compare accounts of the same foretold event. The patron query lists all five tags. Valdris grants +1 in six situations across seven archetypes, including social Deception for rogues and spies. Valdris clerics and oracles increase the Turn Undead/Hollow save DC by 1. Lawful Command gives Valdris marshals +1 initiative when enemies start combat at a tagged sanctuary. Measured Reprisal adds 1 damage when a Valdris warrior hits a foe that attacked a yielded ally in the encounter. Witness Shield gives Valdris guardians +1 AC against attackers named in encounter testimony while the witness is present. Mortaen’s mage spell-attack bonus is dormant until undead creature content exists. The human approved synergy magnitudes; the Unbound visibility, action/reaction-free Raw Channeling, Sovereign Mastery, patron exclusion and combined-test criteria are closed. M8.2 ships Hearthfire and Unravel Fate, so no patron engine ability is pending; full patron playability remains open. See [REMAINING.md](REMAINING.md). |
| 9 · Economy | [09_economy.md](09_economy.md) | 🟡 Partial | 5/83 ACs | Pricing, reputation and inventory substrate; Phase 7 integration remains. See [REMAINING.md](REMAINING.md). |
| 10 · Terrain | [10_terrain.md](10_terrain.md) | ✅ Complete (sprint-1001) | 17/17 ACs | Required terrain, primal/Korath/Druid gates and persisted combat caching shipped. **†Veil Ward** |
| 11 · World Loop | [11_world_loop.md](11_world_loop.md) | ⬜ Not started | 0/46 ACs | Clock/scheduler/cascade criteria remain open; bounded consumer and worker evidence in [REMAINING.md](REMAINING.md). **†Veil Ward** |
| 12 · Story Content | [12_story_content.md](12_story_content.md) | ⬜ Not started | 0/34 ACs | Planned. |
| 13 · First Share | [13_first_share.md](13_first_share.md) | 🟡 Partial | 32/36 ACs | Session 1: 9/9. The walk from creation to a queued whisper exercises caster pools, persisted rider, silence hints and fragment settlement through the session lifecycle; no repeat after consumption and worker restart at favor zero. Session 2 has seven checked criteria; finding the journal grants it and completes the search. Artifact choices persist once with their effects. Fresh recap takeover and failure paths are exercised. Leave delivers the recap before disconnect or returns home after 15 seconds. |
| 14 · Engine Completeness | [14_engine_completeness.md](14_engine_completeness.md) | 🟡 Partial | 3/114 ACs | Base mechanics, gameplay systems, audio and HUD, multiplayer and social, and platform. |
| 15 · Content Coverage | [15_content_coverage.md](15_content_coverage.md) | ⬜ Open | 0/11 ACs | Authored world and story data, from quest hints and encounters to Sessions 4–5. |

> **† Veil Ward.** M24 shipped the location/encounter-scoped, party-wide, duration-bound, multi-source ward model in sprint-040 (`057_veil_ward_scope.sql`), including the Phase 3 source durations and Phase 5 Artificer Veil Anchor recipe. Phase 10 M10.2 ships the Druid terrain gate and ancient-forest discount; Phase 11 owns ambient and Sacred-site world wards.

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

Phase 14 builds on mechanics and player-facing surfaces from the earlier
phases. M14.1 uses Phase 9 denominations for rentals and Phase 11 state for
errand risk. Phase 11's tick integration feeds Phase 12 story machinery.
Phase 15 supplies data to those systems and to Phase 14 gameplay, including
quest guidance and culture placement. Material sell values depend on Phase 9
pricing, where M9.6 also owns merchant inventory pools.

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
| 4 | [04_combat.md](04_combat.md) | `../game_mechanics/game_mechanics_combat.md`, `../game_mechanics/game_mechanics_encounter_roles.md` | 8 |
| 5 | [05_crafting.md](05_crafting.md) | `../game_mechanics/game_mechanics_crafting.md` | 4 |
| 6 | [06_npcs.md](06_npcs.md) | `../game_mechanics/game_mechanics_npcs.md` | 4 |
| 7 | [07_bestiary.md](07_bestiary.md) | `../game_mechanics/game_mechanics_bestiary.md`, `../game_mechanics/game_mechanics_encounter_roles.md` | 4 |
| 8 | [08_patrons.md](08_patrons.md) | `../game_mechanics/game_mechanics_patrons.md` | 3 |
| 9 | [09_economy.md](09_economy.md) | `../game_mechanics/game_mechanics_economy.md` + 6 subsystem docs in `../game_mechanics/economy/` (`supply_demand_engine.md`, `faction_reputation_pricing.md`, `merchant_inventory_restock.md`, `gold_sink_ledger.md`, `inflation_targets_controls.md`, `game_mechanics_p2p_trade.md`) | 10 |
| 10 | [10_terrain.md](10_terrain.md) | `../world_data_simulation.md`, `../game_mechanics/game_mechanics_decisions.md` | 3 |
| 11 | [11_world_loop.md](11_world_loop.md) | `../world_data_simulation.md`, `../technical_architecture.md` | 6 |
| 12 | [12_story_content.md](12_story_content.md) | `../world_data_simulation.md`, `../mvp_spec.md`, `../aethos_lore.md` | 7 |
| 13 | [13_first_share.md](13_first_share.md) | `../mvp_spec.md` | 1 |
| 14 | [14_engine_completeness.md](14_engine_completeness.md) | Game design, mechanics, audio and architecture references in the phase doc | 5 |
| 15 | [15_content_coverage.md](15_content_coverage.md) | World data, MVP, lore and content references in the phase doc | 1 |

**Total: 75 milestones in the phase files listed above**

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

Sprint-007 (M7) reconciled the original phase counts, source-doc paths and dependency graph with the audit corpus. Per-phase audit findings live in [`audit/`](audit/); the
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
