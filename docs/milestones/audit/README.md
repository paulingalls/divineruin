# Milestone Audit — Findings Index

Read-only audit of `docs/milestones/` against shipped code and current spec docs. Sprint-001 covered Phases 0 + 1; Sprint-002 covered Phases 2 + 3 + 8 (Group A); Sprint-003 covered Phases 4 + 7 + encounter_roles overlay (Group B); Sprint-004 covered Phase 5 Crafting (M5.1-M5.4); Sprint-005 covered Phase 6 NPCs (M6.1-M6.4). Findings are consolidated into the milestone files by each sprint's capstone story.

Bias is toward unchecking when evidence is weak — Honesty over optimistic tracking.

## Sprint-001 findings files (Phases 0 + 1)

| File | Scope | Confirmed | Aspirational | Unverified |
| --- | --- | --- | --- | --- |
| [phase-0.md](./phase-0.md) | M0.1–M0.4 doc updates (CLAUDE.md, INDEX.md, gp→gc, cross-refs) | 18 | 4 | 1 |
| [phase-1-rules-engine.md](./phase-1-rules-engine.md) | M1.1 d20 resolution + M1.2 skill tiers | 14 | 0 | 0 |
| [phase-1-characters.md](./phase-1-characters.md) | M1.3 resource pools (incl. 18 archetypes) + M1.4 leveling | 30 | 1 | 2 |
| [phase-1-async.md](./phase-1-async.md) | M1.5 async training + M1.6 companion errands | 11 | 5 | 0 |
| [dependency-versions.md](./dependency-versions.md) | Companion audit: Python, Bun/TS, Expo/RN pinned vs upstream | informational | — | — |

`dependency-versions.md` is informational — not consumed by the capstone; surfaces upgrade recommendations (now / next-sprint / hold) for separate planning.

## Sprint-002 findings files (Phases 2 + 3 + 8 — Group A)

| File | Scope | Confirmed | Partial | Aspirational | Divergent / NOT_SHIPPED |
| --- | --- | --- | --- | --- | --- |
| [phase-2-archetypes.md](./phase-2-archetypes.md) | M2.1 chassis + M2.2 abilities + M2.3 specialization + M2.4 spells + M2.5 mentors | 2 | 5 | 28 | 2 divergent |
| [phase-3-magic.md](./phase-3-magic.md) | M3.1 Resonance + M3.2 Hollow Echo + M3.3 spell catalog + M3.4 concentration / racial | 0 | 0 | 0 | 34 NOT_SHIPPED |
| [phase-8-patrons.md](./phase-8-patrons.md) | M8.1 profiles + favor + M8.2 tier abilities + M8.3 synergies + Unbound | 0 | — | 33 | 1 unverified |

Sprint-002 headline: Group A is **almost entirely unshipped**. Phase 3 Magic is fully NOT_SHIPPED (blocks Phase 8 Layer 2). Phase 8 Patrons has only a thin `divine_favor` integer + god-whisper layer. Phase 2 Archetypes has HP scaling + resource-type assignment confirmed; everything else (DB tables, content seeds, agent tools, mobile UI) is aspirational.

## Sprint-003 findings files (Phases 4 + 7 + encounter_roles — Group B)

| File | Scope | Confirmed | Partial | Divergent | Aspirational / NOT_SHIPPED |
| --- | --- | --- | --- | --- | --- |
| [phase-4-combat.md](./phase-4-combat.md) | M4.1 phase combat + M4.2 action economy + M4.3 conditions + M4.4 death + M4.5 dramatic dice + M4.6 social/travel/gathering | 8 | 9 | 3 | 45 |
| [phase-7-bestiary.md](./phase-7-bestiary.md) | M7.1 stat block schema + M7.2 regional catalog + M7.3 Hollow special mechanics + M7.4 loot/harvesting/encounter builder | 0 | 1 | — | 40 NOT_SHIPPED |
| [phase-encounter-roles.md](./phase-encounter-roles.md) | 790L gm_encounter_roles overlay; ownership map across phases 04 (primary) / 07 / 09 | 0 | 1 | — | 30 NOT_SHIPPED |

Sprint-003 headline: Group B is **almost entirely unshipped**. Phase 4 ships core combat math (AC, attack roll, damage doubling, death save) + a turn-based LLM tool loop — but the spec's 4-beat phase machine, full condition system, dramatic-dice flag, social/travel/gathering, and Mortaen scene wiring are aspirational. Phase 7 is unshipped at every layer (no `content/creatures.json`, no schema, no agent tools). encounter_roles overlay (added after the original milestones) is 0% built across all 9 spec sections.

## Sprint-004 findings files (Phase 5 — Crafting)

| File | Scope | BUILT | DESIGNED | NOT_SHIPPED |
| --- | --- | --- | --- | --- |
| [phase-5-recipes-resolution.md](./phase-5-recipes-resolution.md) | M5.1 recipe & material system + M5.2 workspace & crafting resolution | 0 | 4 | 17 |
| [phase-5-quality.md](./phase-5-quality.md) | M5.3 quality outcomes & experimentation | 0 | 4 | 6 |
| [phase-5-durability.md](./phase-5-durability.md) | M5.4 durability & item catalog | 0 | 4 | 9 |

Sprint-004 headline: Phase 5 is **almost entirely unshipped**. A 4-recipe TS source-of-truth in `apps/server/src/activity_templates.ts:94-130` and a divergent 4-tier resolver in `apps/agent/async_rules.py:34-129` exist; everything else (recipe slots, three-track acquisition, materials catalog, workspace types, three-check pipeline, spec-aligned quality bands, bonus/flaw tables, experimentation, durability system, magic-item content + tier gating) is aspirational. The `Item` interface ships ~13 fields but is missing damage_dice, AC, durability, attunement, audio_cue, and a Rare/Legendary tier widening. No crafting-related DB migrations among the 17 in `scripts/migrations/`.

### Status legend (Sprint-004)

Sprint-004 audits use **BUILT / DESIGNED / NOT_SHIPPED** in place of Sprint-002/003's **confirmed / aspirational (and unverified)**. The mapping is:
- `BUILT` ↔ `confirmed` (code present and matches spec)
- `DESIGNED` ↔ `aspirational` + `unverified` (spec is well-defined and partial code exists, but the symbol/feature is missing, renamed, or diverges from spec)
- `NOT_SHIPPED` is unchanged across all sprints

### Audit Status block layout (Sprint-004)

Sprint-004 evolves the in-milestone block layout: per-milestone H3 blocks (`### Audit Status (Sprint-004)`) placed after each milestone's `**Key references:**` section, rather than a single per-phase H2 block at file top (Sprint-002/003 convention). The per-milestone layout makes the audit context discoverable next to the milestone definition it describes; the H3 level avoids the H2-inside-H3 outline inversion that would otherwise absorb subsequent milestone content. The substring grep `## Audit Status` still matches both `##` and `### Audit Status` lines.

## Sprint-005 findings files (Phase 6 — NPCs)

| File | Scope | BUILT | DESIGNED | NOT_SHIPPED |
| --- | --- | --- | --- | --- |
| [phase-6-schema-archetypes.md](./phase-6-schema-archetypes.md) | M6.1 NPC stat block schema + 12 role archetype templates | 1 | 1 | 6 |
| [phase-6-settlements.md](./phase-6-settlements.md) | M6.2 settlement templates + NPC population + 4 hostile encounters | 0 | 0 | 8 |
| [phase-6-mentors.md](./phase-6-mentors.md) | M6.3 mentor registry + training (Warrior 16 + Rogue 6 + others) | 0 | 2 | 7 |
| [phase-6-companions.md](./phase-6-companions.md) | M6.4 companion profiles + scaling + 5 relationship tiers | 1 | 3 | 5 |

Sprint-005 headline: Phase 6 is **mostly unshipped at the mechanical layer** (2 BUILT / 6 DESIGNED / 26 NOT_SHIPPED across 34 acceptance items) — but the narrative + companion-presence infrastructure underneath it is real. What ships: NPC schema covers narrative/social/disposition (`packages/shared/src/entities/npc.ts:17-39`); `filter_knowledge` enforces disposition-gated knowledge at `apps/agent/tool_support.py:86-105`; CompanionState + companion-in-combat as `CombatParticipant` + idle speech + 4 companion narration shims ship for the presence layer; async training state machine + 4 programs + 8 activity types (including `technique_mentor`) ship as M6.3 infrastructure (variant binding does not). What does NOT ship: 12 role archetype templates, 5 settlement tiers, 8 personality traits, the mentor-variant registry, 3 of 4 companion combat profiles, HP scaling, the 4 hostile encounter templates as content, `content/companions.json`, all 5 deliverable rules-engine functions / agent tools across the 4 milestones. Compound dep: M6.3 ability-link (acceptance bullet 8) is structurally NOT_SHIPPED because M2.5 itself is 0/1/6 per sprint-002 audit.

### Status legend (Sprint-005)

Sprint-005 audits reuse the **BUILT / DESIGNED / NOT_SHIPPED** legend Sprint-004 introduced. The cross-sprint mapping (also documented in the Sprint-004 §Status legend above) is: `BUILT` ↔ Sprint-002/003 `confirmed`; `DESIGNED` ↔ Sprint-002/003 `aspirational` + `unverified`; `NOT_SHIPPED` is unchanged across all sprints. Future audit retros should refer to this consolidated mapping rather than rediscover the bridge each sprint.

### Audit Status block layout (Sprint-005)

Sprint-005 inherits Sprint-004's per-milestone H3 layout — `### Audit Status (Sprint-005)` blocks placed after each milestone's `**Key references:**` section in `docs/milestones/06_npcs.md` (M6.1-M6.4). The substring grep `## Audit Status` matches `##` and `### Audit Status` lines across both sprints.

## Sprint-006 findings files (Phase 9 — Economy)

| File | Scope | BUILT | DESIGNED | NOT_SHIPPED |
| --- | --- | --- | --- | --- |
| [phase-9-economy.md](./phase-9-economy.md) | gm_economy.md base spec (currency / anchor / price tables / NPC services / workspace / commissions / mentor fees / starting gold / merchant pricing / quest rewards / Hollow materials / currency drops) | 0 | 6 | 14 |
| [phase-9-supply-demand.md](./phase-9-supply-demand.md) | economy/supply_demand_engine.md (15 events × 3-phase lifecycle × multiplicative-stack pricing × economic-tag taxonomy × simulation tick + DM narration + decisions 96-104) | 0 | 4 | 39 |
| [phase-9-faction-pricing.md](./phase-9-faction-pricing.md) | economy/faction_reputation_pricing.md (6-tier ladder × price modifiers × service refusal × 5+5 reputation actions × faction-exclusive access × decisions 82-86) | 0 | 3 | 31 |
| [phase-9-restock.md](./phase-9-restock.md) | economy/merchant_inventory_restock.md (3-tier stock × 7 pools × 5×6 settlement size×personality × daily restock × merchant gold pool × consignment × traveling merchants × decisions 87-95) | 0 | 6 | 56 |
| [phase-9-gold-sink.md](./phase-9-gold-sink.md) | economy/gold_sink_ledger.md (8 sink categories + 5 gap-analysis proposals + sink event log + decisions 105-113 — explicitly a consolidation audit per spec L3) | 0 | 3 | 57 |
| [phase-9-inflation.md](./phase-9-inflation.md) | economy/inflation_targets_controls.md (Phase 1 wealth curve + faucet event log + 5 aggregate metrics + Phase 2+ god-agent intervention + 6 seasonal events + decisions 114-121) | 0 | 3 | 60 |
| [phase-9-p2p-trade.md](./phase-9-p2p-trade.md) | economy/game_mechanics_p2p_trade.md (Phase 2+ deferred; audit verifies 4 Phase 1 supporting-infrastructure items + 6 anti-fraud guardrails + decisions 122-128) | 0 | 3 | 41 |

Sprint-006 headline: Phase 9 Economy is **~91% NOT_SHIPPED across 326 acceptance items** (0 BUILT / 28 DESIGNED / 298 NOT_SHIPPED). Substrate ships at narrow touchpoints: `Item.value_base` + `value_modifiers` schema + ~12 typed content items (denominations diverge from spec sp by 12-50×); `starting_gold:int` per archetype (Diplomat=25 vs spec=15); `Npc.disposition_modifiers` (field-name collides with spec mechanic — code carries event-deltas, spec means price-tier multipliers); `Npc.inventory_pool` field BUILT (0 of 14 NPCs populate); `inventory_pools` + `factions` + `player_reputation` + `world_events_log` tables BUILT but **player_reputation and inventory_pools are read by zero code**; `Faction.reputation_tiers` with all 6 spec tiers + EXACT spec thresholds (-10/-5/0/+5/+15/+25) BUILT on 4 factions — strongest substrate of any subsystem; `god_whispers` + `god_whisper_generator` BUILT (patron-id-driven not economic-state-driven); `rest_mechanics.py` BUILT (no lodging-cost gating); `add_to_inventory.source: str` BUILT as free-text provenance seam (structured trail + per-instance UUID NOT_SHIPPED); asyncpg `conn` plumbing BUILT across 22 mutation sites (atomic-trade primitive NOT_SHIPPED). **The pricing-formula pipeline that consumes all this substrate (`calculate_price` → disposition × faction × event × context × clamp) does not exist anywhere in code.**

Phase 9 capstone consolidated 7 audits into a rewritten `09_economy.md` (21 items → ~80 items, 10 milestones M9.1-M9.10). Capstone decision `m9-rewrite-single-file`: kept single file with subsystem subsections.

### Status legend (Sprint-006)

Sprint-006 reuses the **BUILT / DESIGNED / NOT_SHIPPED** legend established in Sprint-004 and carried through Sprint-005. The cross-sprint mapping is documented under §Status legend (Sprint-004) above: `BUILT` ↔ Sprint-002/003 `confirmed`; `DESIGNED` ↔ Sprint-002/003 `aspirational` + `unverified`; `NOT_SHIPPED` is unchanged across all sprints. Sprint-006 audits also use sub-labels `DESIGNED↔confirmed` (schema/content matches spec but no consumer code), `DESIGNED↔aspirational` (partial code exists, structured spec form NOT_SHIPPED), and `DESIGNED↔divergent` (code exists with different mechanic from spec) where the distinction matters for capstone routing.

### Audit Status block layout (Sprint-006)

Sprint-006 inherits Sprint-005's per-milestone H3 layout — `### Audit Status (Sprint-006) — M9.x` blocks placed after each milestone's `**Key references:**` section in `docs/milestones/09_economy.md`. The substring grep `## Audit Status` matches `##` and `### Audit Status` lines across all sprints.

### Decisions 73-128 consolidation (resolved pre-close)

Every sprint-006 audit story (002 through 007) recorded a finding that its source spec doc claimed `> Extracted to game_mechanics_decisions.md for canonical reference` while the canonical decisions log terminated at Decision 72. **The audit framing initially called this a "false-extraction pattern" / "undocumented decisions" — that overstated the gap.** Accurate framing: the decisions **always existed** as inlined `## Design Decisions` sections at the bottom of each source spec doc (e.g. `faction_reputation_pricing.md:173-185` carries decisions 82-86 verbatim). What was missing was the **consolidation step** from source spec → canonical aggregator. Different defect class than "undocumented" implied. Resolved pre-close by commit `884adeb`: decisions 73-128 extracted into the canonical log (56 new entries spanning Encounter Roles / Faction Pricing / Merchant Inventory / Supply & Demand / Gold Sinks / Inflation / P2P Trade). Source spec docs retain their inlined Design Decisions sections for self-contained reading; canonical log is the audit anchor. Framing concern `d47df1654ba0` records the calibration slip for retro learning.

## Material gaps surfaced (capstone annotations)

These were unchecked in `00_doc_updates.md` / `01_core_systems.md` with `<!-- see audit/<file> -->` pointers:

**Phase 0 documentation**
- `game_mechanics_magic.md:423,432` retains `gp` references (Revivify/Resurrection diamond components, explicitly named M0.3 targets); `economy/game_mechanics_p2p_trade.md:160` has a third instance.
- `INDEX.md` line ranges for `game_mechanics_archetypes.md` are off by ~133 lines (file is 1357 lines, INDEX claims 1224).
- `game_mechanics/` docs are not listed in CLAUDE.md's Knowledge System section — reachable only transitively via `INDEX.md`.
- M0.4 "no existing content deleted" cannot be verified positively without a pre-M0.4 baseline.

**Phase 1 leveling (M1.4)**
- Specialization fork: only L5 carries `specialization_fork=True`; L4 emits `elective_techniques` milestone but is NOT flagged as a fork. Spec was reworded to L5-only by sprint-008 per `game_mechanics_core.md L656` "L5 = identity".
- "Unified" progression table covers attribute points + milestones + proficiency + fork in `leveling.py:LEVEL_PROGRESSION`, but HP gain lives separately in `hp_scaling.py:ARCHETYPE_HP_CONFIG`. Acceptance text names HP as a unified-table field.
- `apply_level_up` deliverable struck by sprint-008. Level-up is emitted by `award_xp` / `complete_quest` via `check_level_up` + `LEVEL_UP` event; AC narration satisfied. See `01_core_systems.md §M1.4 Verification footer`.
- `level_for_xp(total_xp) -> int` shipped at `apps/agent/rules_engine.py:274` (sprint-008 story-002). Canonical implementation; `check_level_up` now delegates via `max(current_level, level_for_xp(new_xp))`.
- 18 archetypes encoded in `apps/agent/rules_engine.py` + `hp_scaling.py`, not in `content/archetypes/` (no such directory).

**Phase 1 async (M1.5/M1.6)**
- Companion errand duration ranges: ALL 4 diverge from spec (scout 2–4 vs 4–8 hr; social 1–3 vs 3–6; acquire 2–4 vs 4–10; relationship 3–6 vs 2–4).
- Risk distribution table partial: only `scout` populated at full spec values; `acquire` reduced; `social`/`relationship` always 0/0; several danger×errand combos blocked at validation.
- **Artificer slot exception is dead code:** `validateSlotAvailability` accepts `archetype` + `hasPortableLab` params and is unit-tested, but both call sites in `activities.ts` pass neither. A live Artificer with a Portable Lab cannot benefit from the exception.
- 4 agent-tool deliverables missing as `@function_tool`s — HTTP-only paths: `initiate_training_cycle`, `resolve_training_midpoint`, `dispatch_companion_errand`, `resolve_companion_errand`.
- `training_activities` schema flattens spec's typed columns into `data JSONB` (behavioral fields present in payload).
- Client training "panel" is delivered as Catch-Up feed integration, not a stand-alone screen.

## Sprint-002 capstone annotations (Phases 2 + 3 + 8)

These were captured as "Audit Status (Sprint-002)" blocks at the top of `02_archetypes.md`, `03_magic.md`, `08_patrons.md` with `<!-- see audit/<file> -->` pointers. No M2.x / M3.x / M8.x acceptance boxes were unchecked because all were already `[ ]` — the milestone-level status was re-flagged as DEFERRED / NOT_STARTED in each file.

**Phase 2 — Archetypes (Group A)**
- M2.1: DB table, `content/archetypes.json`, `get_archetype_chassis()` aspirational. HP scaling + resource-type assignment confirmed (Sprint-001 carryover). Stale `ClassData.hit_die` field diverges from `ARCHETYPE_HP_CONFIG`.
- M2.2: Entire ability system aspirational. Only L4/L8 milestone *markers* exist in `LEVEL_PROGRESSION`.
- M2.3: L5 `specialization_fork=True` flag confirmed; per-archetype option pairs (Battle Master / Berserker etc.), `resolve_milestone` tool, mobile UI aspirational.
- M2.4: Spell system aspirational. Training infra uses real-time seconds, not spec's discrete "cycles". `spell_minor` tier missing from training activity types.
- M2.5: Mentor system aspirational. 2 mentor NPC personality stubs + generic state machine exist but are not bound to abilities or variants.

**Phase 3 — Magic (Group A)**
- All M3.1–M3.4 NOT_SHIPPED (34 / 34 criteria). No Resonance state, no spell catalog, no concentration, no racial Resonance bonuses, no Hollow Echo table, no Veil Ward mechanics.
- `content/spells.json` does not exist. Spec is internally consistent at 87 spells.
- `request_attack(target_id, weapon_or_spell)` at `apps/agent/combat_tools.py:275` is NOT a spell-cast tool (no catalog validation, no Focus/Resonance/concentration interaction).
- Spec/milestone divergence on Draethar Inner Fire cost: spec says "1d6 fire damage", milestone says "HP or Focus".
- Stale `gp` refs at `magic.md:423, 432` (Revivify + Resurrection diamonds) carried over from sprint-001 phase-0 audit — still on the M0.3 cleanup punch list.

**Phase 8 — Patrons (Group A)**
- All M8.1–M8.3 aspirational except Unbound Path *selectable* (M8.1 row "unverified").
- `content/gods.json` 60% incomplete (4 of 10 patrons present, no mechanical layer data).
- 4-layer architecture not encoded. Favor is a single-integer 0-100 scale, not tiered. Alignment evaluation is LLM-driven (`award_divine_favor`), not rules-engine-driven (`evaluate_patron_alignment`).
- Layer 4 synergy in `DeityData.synergy_classes` is a flat tuple — needs (11 × 18) matrix with Natural/Divine/Unexpected tagging.

## Sprint-003 capstone annotations (Phases 4 + 7 + encounter_roles)

These were captured as "Audit Status (Sprint-003)" blocks at the top of `04_combat.md`, `07_bestiary.md`, and `09_economy.md` (cross-ref) with `<!-- see audit/<file> -->` pointers. No M4.x / M7.x acceptance boxes were unchecked because all were already `[ ]` — the milestone-level status was re-flagged as DEFERRED / NOT_STARTED in each file.

**Phase 4 — Combat (Group B)**
- M4.1: Turn-based free-form LLM tool loop shipped (`combat_agent.py:26-44`, `session_data.py:46-52`); 4-beat phase machine + Redis state + `advance_combat_phase` aspirational. Initiative (d20+DEX) confirmed. State persistence in `combat_instances` JSONB diverges from spec's `combat_encounters` schema.
- M4.2: Core math confirmed — `calculate_ac`, `resolve_attack` (with crit doubling), proficiency bonus. Weapon damage tops at 1d8 (spec calls for 1d12); damage adds no attribute modifier (spec calls for it). 6 declaration types + enhancers absent.
- M4.3: Entire condition system aspirational — no `character_conditions` table, no apply/tick/remove. `fatigue_narration` is dead-end narrative cue code.
- M4.4: Death save mechanic confirmed (3 success/3 fail, d20 no modifier). Mortaen scene, cost engine, anchor points, Hollowed death, instant death, party wipe, companion auto-stabilize all aspirational.
- M4.5: Entirely aspirational. No `evaluate_dramatic_context`, no `dramatic` flag on any roll result.
- M4.6: All aspirational. NPC disposition infrastructure exists (5-tier `["hostile","wary","neutral","friendly","trusted"]`) but unused; naming divergences flagged (wary↔unfriendly, Fast/Normal/Careful↔Compressed/Scenic/Dangerous).
- **M4.7 proposed (capstone decision `m4-7-overlay-status`)**: new milestone for the encounter_roles overlay (Minion/Standard/Elite/Boss/Named) with stat-modifier table, Elite enhancement, Boss signature/legendary, encounter budget points, role-derivation functions. Author in a future sprint.

**Phase 7 — Bestiary (Group B)**
- M7.1-M7.4: ALL NOT_SHIPPED (40/40 acceptance items). `content/creatures.json` does not exist; no schema validators; no agent tools.
- Only shipped artifact: `content/encounter_templates.json` (6 templates) with flat enemy schema divergent from the M7.1 universal stat block.
- **M7.2 region-count gap (decision `m7-2-creature-count-gap`)**: narrow milestone text to "19+ natural creatures" (path b) — spec authors 19, milestone claims 38+; Ashmark Soldier and Cult Acolyte missing stat blocks despite lore references.
- **M7.1 schema must extend** with optional `role` field and Boss-only `signature_ability` + `legendary_actions[]` for M4.7 alignment.
- **M7.4 `build_encounter` signature (decision `m7-4-build-encounter-signature`)**: capstone records both `(tier, combatant_count, environment)` and `(tier, budget_points, environment)` shapes; final choice deferred to the M4.7/M7.4 implementation sprint.
- M7.3 blocked on Phase 3 Resonance NOT_SHIPPED (sprint-002 carryover).

**encounter_roles overlay (Group B, primary owner Phase 04)**
- 0% built across all 9 spec sections (Role Definitions, Combat Stat Modifiers, Loot Modifiers + Currency Drops + Material Sell Values, XP Modifiers, Encounter Budget System, Worked Examples, DM Narration Guidance, Derivation Formula, Design Decisions 73-81).
- `EncounterRole` enum, role modifier tables, Boss signature/legendary action handlers, encounter budget calculator, material sell-value lookup — all aspirational.
- Phase 04 primary; Phase 07 cross-refs schema; Phase 09 owns currency drops + material sell values (deferred to Phase 09 rewrite per decision `m9-4-loot-economy-status`).

## Sprint-004 capstone annotations (Phase 5 — Crafting)

These were captured as "Audit Status (Sprint-004)" H3 blocks under each milestone in `05_crafting.md` with `<!-- see audit/phase-5-<file>.md -->` pointers. No M5.x acceptance boxes were unchecked because all were already `[ ]` — the milestone-level status was re-flagged as DEFERRED / NOT_STARTED in each block.

**Phase 5 — Crafting (Group C — solo)**
- M5.1: Recipe schema is 4 fields of 13 (TS-only `CraftingRecipe`; no Python class). `content/recipes.json` doesn't exist (4 server recipes ≈ 5% of 70+ target). `recipe_slots` / `player_known_recipes` / `materials_catalog` / `recipes` migrations: none of 17 created. Discovery acquisition track cannot fire (no schematic item type). Spec/milestone conflict: Untrained slot capacity 0 (milestone) vs 3 (spec).
- M5.2: No `Workspace` enum / rental cost table / three-check gate. `async_rules.resolve_crafting()` runs the d20 roll with zero pre-flight checks; server validation is recipe-id existence only. Roll formula matches spec, but `craft_skill` falls back to `"arcana"` (spec: `"crafting"`) and 0 of 4 shipped recipes use the registered `"crafting"` skill. Spec/milestone conflict: rental disposition surcharge for hostile (milestone) vs neutral-or-better gate with refusal at unfriendly (spec).
- M5.3: 4-tier resolver shipped but bands diverge (code's `success` lumps spec's Exceptional+Success; code's `unexpected` has no spec mapping). No per-category bonus-property or flaw tables. No `apply_quality_outcome` / `resolve_experimentation` / `experiment_with_materials` symbols. Spec/milestone conflict: code returns half materials on Failure (`async_rules.py:88-91`); spec is explicit "Materials consumed. Nothing produced."
- M5.4: Entire durability system unshipped. `Item` interface missing 7+ fields (damage_dice, AC, properties, durability, attunement, audio_cue, magic-tier gate). `content/items.json` ~34% catalog coverage by count, ~0% by structured fields. Spec/milestone conflicts: repair-pricing axis (spec: rarity-tier; milestone: durability-tier + damage-level); Legendary "Thornridge's Stand" `Cannot be crafted` quest-only exception breaks the magic-item crafting-tier gate; `Item.tier: 1 | 2` is undersized (need 1-4).

## Sprint-005 capstone annotations (Phase 6 — NPCs)

These were captured as "Audit Status (Sprint-005)" H3 blocks under each milestone in `06_npcs.md` with `<!-- see audit/phase-6-<file>.md -->` pointers. No M6.x acceptance boxes were unchecked because all were already `[ ]` — the milestone-level status was re-flagged as DESIGNED / NOT_STARTED / PARTIAL in each block.

**Phase 6 schema + archetypes (M6.1)**
- **Quest Giver archetype is NEW vs milestone's 12** — spec L190-206 explicitly notes "Not a standalone role — a function layered onto any NPC role." Either treat as `quest_giver?: bool` flag or add a function-overlay deliverable. (sprint-005 phase-6-schema-archetypes)
- **Shipwright archetype is NEW vs milestone's 12** — spec L370-375 ships the 13th archetype; milestone undercounts by 1. (sprint-005 phase-6-schema-archetypes)
- **CreatureStatBlock base type unshipped** — spec L18 has NPCStatBlock inherit from CreatureStatBlock; the base type is Phase 7 territory and not shipped. M6.1 either inlines combat fields or waits on Phase 7. (sprint-005 phase-6-schema-archetypes)
- **`tier: 1|2` vs spec `npc_tier: int` naming** — shipped TS uses `tier`; spec uses `npc_tier`. Pick one when M6.1 schema lands. (sprint-005 phase-6-schema-archetypes)
- **`age?: string` vs spec `age_range: str` enum** — TS shipped a free-form field; spec wants a constrained enum (`"young" | "middle" | "elder"`). (sprint-005 phase-6-schema-archetypes)

**Phase 6 settlements (M6.2)**
- **Capital tier has zero in-world examples** — spec L556 explicitly states "None currently exist — the Sundering destroyed the great cities"; milestone L54-55 wants "full role coverage with named authored NPCs." Capital is post-launch content or the milestone should drop it from "5 tiers." (sprint-005 phase-6-settlements)
- **Hamlet role-count divergence** — milestone L52 says "1 innkeeper, 1 merchant, 1 healer (partial)"; spec L562-578 says 0-1 innkeeper, 0 merchants, 0 healers (herbalist at best). Milestone overcounts vs spec. (sprint-005 phase-6-settlements)
- **`region_type` vs `settlement_tier` orthogonality** — `content/locations.json` already uses `region_type` ∈ {city, wilderness, dungeon}; M6.2 introduces `settlement_tier` (Hamlet→Capital) as a parallel axis. NOT the same thing. (sprint-005 phase-6-settlements)
- **`hollow_patrol_greyvale` name collision** — shipped encounter is name-adjacent to spec's Ashmark Patrol but Hollow-themed (composition is Hollow creatures, not Ashmark soldiers). M6.2 should add Ashmark Patrol as a new template. (sprint-005 phase-6-settlements)
- **Settlement role-distribution table has no Capital column** — spec L560-578 covers Hamlet/Village/Town/City only despite Capital being a defined tier. (sprint-005 phase-6-settlements)
- **Reputation-aware encounter selection** — Ashmark Patrol's allied/hostile flip by Thornwatch standing (spec L613) is NEW vs milestone — reputation-aware encounter behavior is not in the acceptance list. (sprint-005 phase-6-settlements)

**Phase 6 mentor registry (M6.3)**
- **Warrior mentor count undercount** — milestone says "8+ mentors"; spec ships 16 variants across 8 techniques. Real coverage target is 16. (sprint-005 phase-6-mentors)
- **Guardian/Skirmisher/Spy/Bard at 1 per archetype** — milestone L97 wants "at least 2"; spec ships exactly 1 representative per archetype. Trim milestone target or extend spec. (sprint-005 phase-6-mentors)
- **Diplomat archetype NEW** — spec section heading L508 enumerates "Guardian, Skirmisher, Spy, Bard, Diplomat Mentors"; milestone drops Diplomat. (sprint-005 phase-6-mentors)
- **`culture` field NEW vs milestone deliverables** — mentor schema spec L390 carries `culture: str` field; milestone L88 enumerates the other 6 schema fields but omits culture. (sprint-005 phase-6-mentors)
- **`seeker_emris` vs `scholar_emris` name disambiguation** — spec L505 names "Seeker-Agent Emris" (Rogue L8 Exploit Weakness mentor); shipped NPC id is `scholar_emris` ("Emris of the Diaspora"). Same character per role match; M6.3 needs to record the alias or rename. (sprint-005 phase-6-mentors)
- **`training_programs.mentor_id` field already binds to non-spec mentors** — `content/training_programs.json` ships 4 entries with `mentor_id` field but only references `guildmaster_torin` and `scholar_emris` for stat-training programs, not technique variants. M6.3 should reuse this binding pattern at the variant level or document why technique-mentor training diverges. (sprint-005 phase-6-mentors)
- **`training_activities.data JSONB` variant_id placement decision** — table ships per-player cycle state with a JSONB extension slot; M6.3 implementation must choose typed `variant_id` column vs JSONB namespace. (sprint-005 phase-6-mentors)

**Phase 6 companions (M6.4)**
- **CompanionState infrastructure NEW vs M6.4 deliverables** — `CompanionState` (`apps/agent/session_data.py:15-24`) ships id/is_present/is_conscious/emotional_state/relationship_tier/session_memories/last_speech_time; `companion_idle.py` ships LLM idle speech; `activity_templates.py:31-78` `COMPANION_CONTEXT` ships 4 narration shims (Kael/Lira/Tam/Sable). M6.4 deliverables don't enumerate this presence layer. Promote to M6.4 or split into a new M6.5 Companion Presence Layer. (sprint-005 phase-6-companions)
- **Errand-bonus relationship_tier coupling** at `apps/agent/async_rules.py:143-147` (`relationship_bonus = min(relationship_tier, 4)`) is NEW out-of-combat mechanic not in M6.4 — doesn't violate bullet 5's negative-condition (relationship doesn't affect combat) but is undocumented. (sprint-005 phase-6-companions)
- **Companion Assignment Logic** (spec L823-849) NEW vs milestone — archetype-complement assignment rule (Mages get Kael, Warriors get Lira) is not in M6.4 deliverables. (sprint-005 phase-6-companions)
- **Companion Progression Milestones** (spec L851-863) NEW vs milestone — per-session milestone framework overlaps M6.4's "5 tiers with narrative gates" with specific session-count anchors. (sprint-005 phase-6-companions)
- **Kael action_pool flat-list vs typed-bucket schema divergence** — `content/npcs.json:147-223` ships `combat_stats.action_pool` as a flat list of 2 untyped entries (Longsword + Defensive Stance); spec wants typed attacks/passives/actives/reactions buckets. NPC schema split decision needed (extend NPC schema vs separate `Companion` interface). (sprint-005 phase-6-companions)
- **Defensive Stance vs spec Shield Bash** — Kael's shipped 2nd action is "Defensive Stance" (grants +2 AC); spec attack #2 is Shield Bash (1d4+STR bludgeoning, stun on save fail). Different mechanic, different name. (sprint-005 phase-6-companions)
- **Sable non-verbal TTS handling** — spec L786-789 explicitly notes Sable "communicates through body language, growls, and pointed looks"; voice-registry decision needed (suppress TTS vs growl sound effects). (sprint-005 phase-6-companions)
- **CompanionState in-memory only** — no per-session persistence for relationship_tier, session_memories. M6.4 deliverable L129 calls for `companions` + `companion_relationships` tables; migration design needed. (sprint-005 phase-6-companions)

## Sprint-006 capstone annotations (Phase 9 — Economy)

These were captured as "Audit Status (Sprint-006) — M9.x" H3 blocks under each milestone in the rewritten `09_economy.md` (M9.1-M9.10) with `<!-- see audit/phase-9-<file>.md -->` pointers. No M9.x acceptance boxes were unchecked — the milestone-level status was flagged DESIGNED↔aspirational / NOT_SHIPPED per row.

**Phase 9 — Currency & Pricing Substrate (M9.1, M9.2, M9.3, M9.4)**
- **Item.value_base denomination divergence** — `packages/shared/src/entities/item.ts:20-21` ships `value_base: number` + `value_modifiers?: Record<string, number>`; `content/items.json` populates ~12 typed items with values that **diverge from spec sp by 12-50×** with no consistent denomination scaling (shortsword_basic=100 vs spec 5sp, longsword_guild=200 vs spec 10sp, dagger_balanced=50 vs spec 2sp). Schema BUILT, anchor unenforced, content divergent. (sprint-006 phase-9-economy)
- **starting_gold divergence** — `apps/agent/creation_classes.py:21` ships `starting_gold: int` across 18 archetypes with values 10/15/20/25. Spec spread is 2 values (10/15). **Diplomat=25 diverges by +10 sp.** (sprint-006 phase-9-economy)
- **Npc.disposition_modifiers field-name collision** — `packages/shared/src/entities/npc.ts:33` ships `disposition_modifiers?: Record<string, number>` populated on 14 NPCs in `content/npcs.json` — but the field carries **per-action disposition deltas** (e.g. `defended_millhaven: 5`), NOT the spec's 5-tier disposition price-modifier table from gm_economy L218-225. Schema-rename or new `price_disposition_modifiers` field required before M9.2 ships. (sprint-006 phase-9-economy)
- **M9.4 Loot-side Economy promoted from sprint-003 decision `m9-4-loot-economy-status`** (previously deferred to the Phase 09 rewrite). Now lands as a numbered milestone covering currency drops + Hollow material values + encounter_roles loot modifiers. Substrate dependencies (Phase 4 M4.7 encounter_roles + Phase 7 M7.1 creature `role` field) are also NOT_SHIPPED per sprint-003 audits.

**Phase 9 — Faction Pricing (M9.5)**
- **Strongest substrate of any Phase 9 subsystem.** `Faction.reputation_tiers` schema BUILT (`faction.ts:1-21`); `factions` + `player_reputation` tables BUILT (migration 001:57-66, 135-143) + `idx_player_reputation_faction` (002:5); `content/factions.json` ships 4 factions, **each populating all 6 spec tiers with EXACT spec thresholds** (-10/-5/0/+5/+15/+25 verified on accord_guild). (sprint-006 phase-9-faction-pricing)
- **`player_reputation` table is BUILT but completely dormant** — zero code reads or writes it. Reputation_value never computed, persisted, or queried. (sprint-006 phase-9-faction-pricing)
- **`ReputationTier.effects: string[]` is narrative prose, not numerical** — e.g. `accord_guild.honored.effects = ["guild council voice", "field authority", "classified intelligence"]`. Schema needs `price_modifier: number` field OR a global tier→modifier constant table. (sprint-006 phase-9-faction-pricing)
- **Content/spec faction-example divergence** — spec uses Thornwatch + Merchant Guild as worked examples (L115-129); shipped 4 factions are accord_guild + aelindran_diaspora + independent + temple_authority. Capstone choice: backfill content vs rewrite spec to use shipped faction ids. (sprint-006 phase-9-faction-pricing)

**Phase 9 — Merchant Inventory & Restock (M9.6)**
- **inventory_pools schema divergence** — shipped pool shape is `{id, name, location, type, restock_interval_hours, items: [{item_id, quantity, price}]}` (flat per-merchant). Spec shape is `{id, tier_1_items, tier_2_items: [{item_id, quantity_by_settlement}], tier_3_items: [{item_id, settlements, presence_chance, restock_check}]}` (type-based reusable with tier classification + settlement-keyed quantities). Capstone choice: restructure content vs adapt spec. (sprint-006 phase-9-restock)
- **Npc.inventory_pool field BUILT but 0 of 14 NPCs populate it** — orphaned content. Merchant→pool binding the schema supports is not used. (sprint-006 phase-9-restock)
- **Pool prices vs Item.value_base co-authoring** — `market_general` + `grimjaw_weapons` pool prices exactly match `Item.value_base`; `temple_supplies` carries -10% discounts; `millhaven_supplies` carries +20-67% markups (directionally consistent with spec Isolated personality +25% but magnitudes overshoot — flagged as hypothesis worth capstone investigation). (sprint-006 phase-9-restock)
- **Location schema lacks settlement-size + personality fields** — `region_type` ships with values {city, wilderness, dungeon} (3-element enum, doesn't represent the spec's 5-element settlement-size axis); 0 of 6 personality traits appear in location tags. Cross-cuts M9.6 + M9.10. (sprint-006 phase-9-restock + phase-9-p2p-trade)
- **add_to_inventory / remove_from_inventory are narrative-only, not merchant-enforcing** — flow is narration → DB write; spec's `attempt_purchase` / `attempt_sale` with stock + gold + buyback enforcement do not exist. (sprint-006 phase-9-restock)

**Phase 9 — Supply & Demand Engine (M9.7)**
- **Event substrate BUILT for narrative news feed, not for price impact** — `world_events_log` table BUILT (migration 001:184-189); 8 records in `content/events.json` (4 scripted + 3 world_event + 1 god_whisper, none `type: "economic"`); `apps/agent/db_mutations.py:228` writes; `apps/agent/world_news.py:39,52-55` reads for player catch-up summaries. JSONB blob could carry the spec's event-instance schema but no shipped code does. (sprint-006 phase-9-supply-demand)
- **Item economic tags partial** — `Item.tags: string[]` is a single narrative+economic tag array. 1 of 11 spec economic tags (`healing`) appears organically on 3 items. No separate `economic_tags: string[]` field; no event-modifier lookup keyed by tag. (sprint-006 phase-9-supply-demand)
- **compute_item_price + economy_simulation_tick + 0.5×–3.0× clamp + 3-phase event lifecycle all NOT_SHIPPED.** (sprint-006 phase-9-supply-demand)
- **`market_disruption` event id is misleading** — id reads economic; type is scripted (narrative beat: "The Wounded Rider"). Capstone: rename or upgrade type. (sprint-006 phase-9-supply-demand)

**Phase 9 — Gold Sink Ledger (M9.8)**
- **`player.gold` is one-write-no-read** — set at character creation (`creation_rules.py:257` writes `"gold": cls.starting_gold`), **never mutated** by any code. No `add_gold` / `consume_gold` / `attempt_charge` mutation surface alongside the read path. (sprint-006 phase-9-gold-sink)
- **rest_mechanics.py BUILT but lodging-cost gating NOT_SHIPPED** — `apply_short_rest` / `apply_long_rest` / `apply_rest` at `apps/agent/rest_mechanics.py:8/20/32` ship as pure functions handling stamina/focus/HP restoration. Take no `lodging_quality` parameter, no cost debit, no quality modifier. A player can long-rest anywhere for free. (sprint-006 phase-9-gold-sink)
- **6 consumable items ship in content/items.json without a consume_item hook** — items exist (healing_potion / antidote_basic / holy_water / rations_basic / millhaven_provisions / restoration_salve); spec needs `consume_item` agent tool that decrements inventory + emits sink_event when used. (sprint-006 phase-9-gold-sink)
- **gold_sink_ledger.md is a consolidation doc** (spec L3) — most sink categories inherit NOT_SHIPPED from source subsystems (Phase 5 durability, Phase 6 mentors, M9.5 donations, M9.6 consignment, M9.2 NPC services). This audit's unique contribution is the 8-category framework, sink_event_log schema, and 5 gap-analysis additions. (sprint-006 phase-9-gold-sink)

**Phase 9 — Inflation Targets & Controls (M9.9)**
- **God roster divergence: Aelora (shipped) vs Aelindra (spec)** — spec L151 names **Aelindra** (Preservation/Memory/Value) as an economic-intervention god; shipped roster (`content/gods.json`) has 10 gods including `aelora` (Civilization/commerce/crafting/community) — sympathetic but distinct deity. Faction `aelindran_diaspora` exists separately. Capstone choice: rename `aelora` → `aelindra` OR rewrite spec to use shipped `aelora`. (sprint-006 phase-9-inflation)
- **God-whisper substrate BUILT, economic-state-driven trigger NOT_SHIPPED** — `god_whispers` table BUILT (migration 009); `god_whisper_generator.py:16` ships; `async_worker.py:396-426` invokes on patron-id triggers, **not faucet/sink drift triggers**. Adding `evaluate_economic_state` heartbeat consideration is the path to activation. (sprint-006 phase-9-inflation)
- **Keldaran faction is referenced but not in content** — spec ships Forge Day (Keldaran-cultural seasonal event) + Keldaran-forged weapons; `content/factions.json` does not ship Keldaran. Multi-layer gap (parallel to Thornwatch + Merchant Guild missing from M9.5). (sprint-006 phase-9-inflation)
- **Patron heartbeat cadence (15-30 min per spec L242) was not separately verified end-to-end in this audit** — conservatively marked DESIGNED based on whisper substrate. Capstone should reconcile against `phase-8-patrons.md` audit findings. (sprint-006 phase-9-inflation)

**Phase 9 — P2P Trade Infrastructure (M9.10 [Phase 2+])**
- **add_to_inventory.source is provenance-shaped but not provenance-structured** — ships at `apps/agent/inventory_tools.py:24-33` with free-text source field (examples: "looted from goblin", "purchased from merchant"). Spec L171 needs ordered list of typed events; shipped is single mutable string. Schema needs `provenance: ProvenanceEvent[]` field on Item OR sibling `item_history` table. (sprint-006 phase-9-p2p-trade)
- **player_inventory PK is on template id, not per-instance UUID** — `(player_id, item_id)` keys on content template (e.g. `healing_potion`), so multiple players' copies share an item-id; spec's "weapon's history" example requires per-copy UUIDs. Schema change required (`item_instance_id UUID` column OR `data.instance_id` convention). (sprint-006 phase-9-p2p-trade)
- **asyncpg conn plumbing BUILT, atomic-trade primitive NOT_SHIPPED** — `apps/agent/db_mutations.py` mutation functions accept `conn: asyncpg.Connection | Pool | None` across 22 sites — substrate for transaction-scoping is real. `atomic_p2p_transfer(from, to, items, gold)` does not exist. (sprint-006 phase-9-p2p-trade)
- **Location.settlement_id gap blocks "same settlement" predicate** (cross-cuts M9.6 + M9.10) — player→location ships (`update_player_location`); `Location.id` is granular (`accord_market_square` ≠ `accord_guild_hall`); no settlement-grouping concept. Spec L184 "are these two players in the same settlement?" cannot be answered in O(1). (sprint-006 phase-9-restock + phase-9-p2p-trade)

## Sprint-spec-cleanup punch list

Out-of-scope-but-real findings surfaced by audits that don't fit any active milestone — collected here so they don't drift between sprints. Add new items at the bottom.

- **Stale `gp` references** in `game_mechanics_magic.md:423` (Revivify diamond "50 gp") and `:432` (Resurrection diamond "500 gp"). Original M0.3 gp→gc cleanup missed these two. Plus a third instance at `economy/game_mechanics_p2p_trade.md:160`. (sprint-001 phase-0 audit; reaffirmed sprint-002 phase-3 audit; concern `027196d5b06f`)
- **`INDEX.md` line ranges off** for `game_mechanics_archetypes.md` (~133 lines drift; file is 1357L, INDEX claims 1224L). (sprint-001 phase-0)
- **`game_mechanics/` docs unlisted in CLAUDE.md** Knowledge System section — reachable only transitively via `INDEX.md`. Remediation: add a bullet under CLAUDE.md "Knowledge System" naming `docs/game_mechanics/` + `docs/game_mechanics/economy/` as the source-of-truth for mechanics specs, with `docs/INDEX.md` as the entry-point. (sprint-001 phase-0)
- **`async_rules.resolve_crafting` default skill** — defaults `craft_skill` to `"arcana"` (`async_rules.py:47`) rather than `"crafting"` (registered at `rules_engine.py:102`). The 4 shipped recipes use `"athletics"` / `"medicine"` / `"arcana"` — 0 use `"crafting"`. Once M5.1 schema lands, recipes should reference the registered skill. (sprint-004 phase-5-recipes-resolution)
- **`async_rules.resolve_crafting` half-materials-on-failure conflict** — `async_rules.py:88-91` returns half the materials when Failure tier fires; spec at `game_mechanics_crafting.md:106` is explicit "Materials consumed. Nothing produced." Resolve when M5.3 (Quality Outcomes) ships. (sprint-004 phase-5-recipes-resolution + phase-5-quality)
- **M5.1 spec/milestone conflict: Untrained recipe slots** — milestone bullet says "Untrained: 0"; spec at `game_mechanics_crafting.md:158` says "Untrained 3". Capstone needs customer resolution. (sprint-004 phase-5-recipes-resolution)
- **M5.2 spec/milestone conflict: rental disposition modifiers** — milestone bullet says "discount for friendly, surcharge for hostile"; spec at `game_mechanics_crafting.md:204-207` gates rental at neutral-or-better (refusal at unfriendly, no surcharge defined). (sprint-004 phase-5-recipes-resolution)
- **M5.4 repair-pricing axis conflict** — spec at `game_mechanics_crafting.md:542-549` keys repair cost on item-rarity-tier (Common/Uncommon/Rare/Legendary); milestone acceptance bullet 4 says "scales with durability tier and current damage level". Different axes — spec or milestone must win. (sprint-004 phase-5-durability)
- **`Item.tier: 1 | 2` undersized** — TS type at `packages/shared/src/entities/item.ts:13` accepts only `1 | 2`; spec defines 4 rarity tiers (1=Common through 4=Legendary). Mechanical breakage when a Rare-tier item lands with `tier: 3`. Widen to `1 | 2 | 3 | 4`. (sprint-004 phase-5-durability)
- **`audio_cue?: string` missing from `Item` interface** — spec magic items carry explicit "Audio:" descriptions (e.g., Blade of the Ashmark "Soft radiant hum when drawn"). CLAUDE.md audio-first invariant should be enforced at the schema layer. (sprint-004 phase-5-durability)
- **Legendary Thornridge's Stand quest-only exception** — `game_mechanics_crafting.md:516` carries "Cannot be crafted"; milestone acceptance bullet 9 assumes all Magic items are gated by crafting tier. Add a `quest_only: bool` field OR record a documented exception list. (sprint-004 phase-5-durability)
- **`Item.value_base` denomination is undocumented** — values in `content/items.json` diverge from spec sp by 12-50× with no consistent scaling. Schema needs an inline denomination comment + a `lookup_base_price(item_id)` helper that anchors the field to spec sp. (sprint-006 phase-9-economy)
- **`Npc.disposition_modifiers` field-name collision with spec disposition-tier price modifier** — code field carries event-deltas (per-action disposition shifts); spec needs price-tier multipliers. Rename one, or add a sibling `price_disposition_modifiers` field, or use a global tier→multiplier constant table. (sprint-006 phase-9-economy)
- **`starting_gold` spec divergence: Diplomat=25 vs spec=15** — 18 archetypes ship values 10/15/20/25 vs spec's 2-value spread (10 baseline / 15 Diplomat). Either reconcile spec or annotate divergence as intentional. (sprint-006 phase-9-economy)
- **NPC services + workspace rental + crafting commissions + mentor fees + hollow material values + currency drops are all spec but absent from the original 21-item M9.x scope** — now landed as new milestones M9.4-M9.8 in the rewritten 09_economy.md. (sprint-006 phase-9-economy)
- **`ReputationTier.price_modifier: number` schema extension** — Faction.reputation_tiers ships `{threshold, effects[]}` only; needs a typed `price_modifier: number` field OR a global tier→modifier constant table. (sprint-006 phase-9-faction-pricing)
- **Faction content/spec divergence: Thornwatch + Merchant Guild + Keldaran** — spec worked examples reference factions not in `content/factions.json` (which ships accord_guild + aelindran_diaspora + independent + temple_authority). Bundle resolution: backfill content, OR rewrite spec to use shipped faction ids. Affects M9.5 + M9.9 (Forge Day Keldaran). (sprint-006 phase-9-faction-pricing + phase-9-inflation)
- **`Faction.reputation_tiers.effects: string[]` is narrative prose with no machine reader** — capstone should decide whether to keep effects narration-only (with `narrate_faction_tier(faction_id, tier)` helper) or replace with typed structured fields (`services_available`, `inventory_unlocks`, `discount_modifier`). (sprint-006 phase-9-faction-pricing)
- **`player_reputation` table BUILT but dormant** — zero reads, zero writes. High-leverage low-cost wiring task when reputation pipeline lands. (sprint-006 phase-9-faction-pricing)
- **NPC merchant→pool binding is BUILT on schema but unused in content** — `Npc.inventory_pool: string | null` ships; 0 of 14 NPCs populate it. Backfill once Phase 6 role archetypes (M6.1) land. (sprint-006 phase-9-restock)
- **`inventory_pools` schema migration** — flat per-merchant `{id, items: [{item_id, quantity, price}]}` → typed-tier per spec L453-480 with `tier_1_items` + `tier_2_items[{quantity_by_settlement}]` + `tier_3_items[{settlements, presence_chance, restock_check}]`. Capstone must pick: (a) restructure content + add NPC binding, (b) change spec to match shipped, or (c) adapter layer. (sprint-006 phase-9-restock)
- **Pool prices vs Item.value_base reconciliation** — `market_general` + `grimjaw_weapons` exact match; `temple_supplies` -10%; `millhaven_supplies` +20-67%. When pricing engine lands, decide between (a) delete pool.price and compute from value_base via formula, (b) rename to `base_price_override`, or (c) hybrid. (sprint-006 phase-9-restock)
- **`Location.size` + `Location.personality` schema fields missing** — needed for spec's 5×6 settlement size×personality stock + gold modifier matrices. `region_type` ships with values {city, wilderness, dungeon} (3-element flat enum, not the spec axis). Cross-cuts M9.6 + M9.10 (settlement_id). (sprint-006 phase-9-restock + phase-9-p2p-trade)
- **Tier classification on items** (Tier 1 always-stocked vs Tier 2 limited vs Tier 3 unique) — needed on `Item` or on pool entries. Spec's narration rules (3-4 highlights) depend on this classification. (sprint-006 phase-9-restock)
- **`restock_interval_hours: 24` field on shipped pools is dormant** — no consumer. When daily_restock_at_dawn lands, decide whether per-pool override is intentional configuration or unused metadata. (sprint-006 phase-9-restock)
- **`Item.economic_tags: string[]` schema extension** — current `Item.tags: string[]` is a single narrative+economic array; 1 of 11 spec economic tags (`healing`) appears organically. Capstone should add a separate field with the 11-tag taxonomy + tag-inheritance convention from material composition. (sprint-006 phase-9-supply-demand)
- **`market_disruption` event id is misleading** — id reads economic, type is `scripted` (narrative beat). Capstone: rename or upgrade type. (sprint-006 phase-9-supply-demand)
- **`world_events_log.data` JSONB schema enforcement** — when economy engine lands, decide whether to enforce a JSONB schema for `type: "economic"` events or introduce a sibling `economy_events` table with explicit columns. (sprint-006 phase-9-supply-demand)
- **`player.gold` mutation surface** — needs `add_gold` / `consume_gold` / `attempt_charge` alongside the read path. Currently one-write-no-read. (sprint-006 phase-9-gold-sink)
- **`consume_item` agent tool** — bridges item.effects[].type=heal data → mechanic (HP add, item decrement, sink event). Without it, DM can narrate a potion drink but the rules engine doesn't fire consequences automatically. (sprint-006 phase-9-gold-sink)
- **`apply_rest` should accept `lodging_quality` parameter** that gates +1 quality bonus and emits sink_event. Small change to a BUILT function; high-leverage low-cost. (sprint-006 phase-9-gold-sink)
- **`sink_event_log` + `faucet_event_log` tables** — required infrastructure for inflation control. Schemas per `gold_sink_ledger.md:389-402` + `inflation_targets_controls.md:86-95`. Both NOT_SHIPPED; both required before M9.8 + M9.9 can ship. (sprint-006 phase-9-gold-sink + phase-9-inflation)
- **God roster: Aelora (shipped) vs Aelindra (spec)** — rename one or accept the mapping. Spec narrative example "Aelindra grants vision" cannot be authored against shipped content as-is. (sprint-006 phase-9-inflation)
- **Wealth-by-level constants need a home** — capstone should decide between `apps/agent/economy_config.py` constants table, JSON file (`content/economy_targets.json`), or DB table. Spec implies tunable (Decision 118 parameter tuning lever); JSON or DB preferable to code constants. (sprint-006 phase-9-inflation)
- **Per-instance item identity** — `player_inventory` PK is `(player_id, item_id)` on content template; spec's "weapon's history" example requires per-copy UUIDs. Capstone should plan `item_instance_id UUID` column or `data.instance_id` UUID convention. (sprint-006 phase-9-p2p-trade)
- **`Location.settlement_id` field** (cross-cuts M9.6 + M9.10) — enables "same settlement" O(1) query. Decide between (a) tag locations with settlement_id string OR (b) introduce typed `Settlement` entity (heavier; supports M9.6 spec gap directly). (sprint-006 phase-9-restock + phase-9-p2p-trade)
- **NPC.faction is the merchant→faction binding** — already on schema (`Npc.faction: string` BUILT per phase-6 audit); spec L48 implies merchant→faction binding. Capstone should clarify whether NPC.faction is the canonical binding or whether a separate `NPC.affiliations` field is needed. (sprint-006 phase-9-faction-pricing)
- **`appreciated_gifts: string[]` field on Npc schema** — low-cost addition that enables NPC gift system (Gap 5 of gold_sink_ledger.md). Bundle with M9.5 faction-pricing schema decisions. (sprint-006 phase-9-gold-sink)
- **`Item.tier` field name collision (sprint-004 + sprint-006)** — sprint-004 punch-list calls for widening `Item.tier: 1|2` to `1|2|3|4` (rarity Common/Uncommon/Rare/Legendary); sprint-006 M9.6 introduces Tier 1/2/3 (stock availability — always/limited/unique). Both compete for the same field name. Capstone proposal: rename one (e.g. `Item.rarity_tier` + `Item.stock_tier`, OR move stock tier to pool entries). (sprint-006 cross-cuts sprint-004 phase-5-durability)
- **`content/events.json` `market_disruption` entry id is misleading** — id reads economic; type is `scripted` (narrative beat "The Wounded Rider"). When M9.7 economic events land with `type: "economic"`, decide whether to rename this entry to disambiguate or upgrade its type. (sprint-006 phase-9-supply-demand)

## Sprint-005 follow-up candidates

Sprint-003 carry-forwards (still open):

- Author **M4.7 "Encounter Role Overlay"** as a numbered milestone in `04_combat.md` (capstone surfaced; not yet authored in the file's milestone list). Scope: `EncounterRole` enum, role modifier table, Elite/Boss enhancement rules, encounter budget points, role-derivation functions.
- Pair **M4.7 + M7.4** implementation in a single sprint so the `build_encounter` signature choice can be resolved with full context (decision `m7-4-build-encounter-signature` is deferred).
- Reconcile **M7.2 milestone text** to "19+ natural creatures" + add Ashmark Soldier / Cult Acolyte stat blocks to spec OR remove them from lore prompts.
- Reconcile **disposition tier naming** (`wary` in code vs `unfriendly` in spec) and **travel-mode naming** (Fast/Normal/Careful in spec vs Compressed/Scenic/Dangerous narrative text) before Phase 4 social/travel work.
- Cross-cut prerequisite: Phase 3 Magic (Resonance system) before M7.3 Hollow creature mechanics can ship.

Sprint-001/002 carry-forwards (still open):

- Resolve surviving `gp` references in `game_mechanics_magic.md` (M0.3 cleanup); update `INDEX.md` line ranges for archetypes.
- ~~Decide M1.4 spec vs code: either rename the fork to L5-only and split HP from the unified table, or update code to match (add `specialization_fork` to L4, fold HP into `LEVEL_PROGRESSION`).~~ **Settled by sprint-008**: spec reworded to L5-only fork (L4=`elective_techniques`); HP kept in `ARCHETYPE_HP_CONFIG` with `build_level_up_payload_for_archetype` as the join helper.
- Decide M1.6 spec vs code: either reduce duration spec to match shipped values, OR widen the shipped risk table to cover all 4 errand types at all danger levels.
- Fix the Artificer slot dead code: pass `archetype` + `hasPortableLab` from `activities.ts` call sites OR remove the unused validator params.
- Add the 4 missing agent tools (initiate_training_cycle, resolve_training_midpoint, dispatch_companion_errand, resolve_companion_errand) OR formally remove them from the deliverable list.

New from sprint-002 audits:

- **Phase 2 capstone work** (large): seed `archetypes` DB table + `content/archetypes.json`; implement `get_archetype_chassis`; ship `archetype_abilities` + `character_abilities` tables + `request_ability_activation` agent tool; encode L4/L8 elective pools; build `resolve_milestone` + mobile L5 fork UI; ship spell tracks (M2.4) — note training durations need conversion from seconds to discrete cycles; ship mentor-variant system (M2.5).
- **Phase 3 capstone work** (largest, blocks Phase 8 Layer 2): ship the entire Resonance system + Hollow Echo + Veil Ward + spell catalog + concentration + racial Resonance. Decide on spec-superset deliverables (Bard 0.4× multiplier, Veythar post-reveal 0.7×, cantrip 0-Resonance, rest reset, Veil Fracture event, Arcana sensing ladder, Druid prep constraint, per-archetype Veil Ward sources).
- **Phase 8 capstone work**: complete `content/gods.json` (6 missing patrons + Layer 1-4 fields for all 10); add tier model + thresholds + decay; ship `evaluate_patron_alignment` / `get_patron_tier` / `activate_patron_ability` / `check_patron_tier` / `get_archetype_synergy` / `apply_unbound_resonance_push` / `query_patron_synergy`; create `patron_ability_unlock` + `archetype_synergy` migrations; build Unbound mechanics (Veil Clarity, voluntary +3 push, Veil Mastery, Self-Reliance milestones).
- **Spec/milestone divergences to reconcile** (capstone choices): M3.4 Draethar Inner Fire cost (spec: fire damage; milestone: HP or Focus — recommend tightening milestone to spec); ~~M2.3 L4/L5 fork wording (Sprint-001 finding still open)~~ **settled by sprint-008** (L5-only fork; L4=`elective_techniques`); M2.4 training durations (seconds vs cycles).

New from sprint-004 audits:

- **Phase 5 capstone work** (largest single phase audited): the entire crafting pipeline is unshipped. Break it down by milestone:
  - **M5.1**: recipe schema (13 fields) + `content/recipes.json` (70+ entries) + `recipes` / `recipe_slots` / `player_known_recipes` / `materials_catalog` migrations + `MaterialReq` shape + 3 acquisition tracks (Recipe Slots / Training / Discovery) + per-tier slot caps + pure functions `validate_recipe_slot_capacity` + `check_material_requirements` + agent tools `learn_recipe` + `query_recipe_requirements`.
  - **M5.2**: 4 workspace types + 4 access methods + NPC disposition-modifier rental pricing + `workspace_rentals` migration + three-check gate pipeline (knowledge / skill-tier / workspace) + pure functions `validate_recipe_knowledge` + `validate_workspace_tier` + `resolve_crafting_check` + agent tools `query_available_workspaces` + `start_crafting_project`.
  - **M5.3**: spec-aligned 4-tier quality bands (Exceptional / Success / Partial / Failure) + per-category bonus-property and flaw tables + Experimentation mechanic (DC+4) + pure functions `apply_quality_outcome` + `resolve_experimentation` + agent tool `experiment_with_materials`.
  - **M5.4**: durability system (4 tiers + hit-depletion + Hollow 2× corrosion) + repair pricing + 6 Rare + 4 Legendary magic items + magic-item-tier gating + `items_catalog` migration + `Item` schema additions (durability, damage_dice, AC, properties, attunement, audio_cue, widen tier to 1-4) + pure functions `apply_durability_damage` + `check_item_condition` + `calculate_repair_cost`.
- **Re-align `async_rules.resolve_crafting`** to spec when M5.3 ships: rename tiers to `Exceptional` / `Success` / `Partial` / `Failure`; fix Failure to consume all materials (not half); replace `quality_bonus: int` with a structured bonus-property payload; drop the spec-less `unexpected` tier.
- **Widen `Item.tier` union** from `1 | 2` to `1 | 2 | 3 | 4` (mechanical blocker — TS type error on any Rare/Legendary item).
- **Add `audio_cue?: string` field** to the `Item` interface so spec magic-item audio cues live in the schema (audio-first invariant).
- **Decouple `CRAFTING_RECIPES.npc_id` hard-binding** (`activity_templates.ts:105` uses `"grimjaw_blacksmith"` across all recipes) — workspace model separates NPC-as-renter from NPC-as-narrator.

New from sprint-005 audits:

- **Phase 6 capstone work** (mechanical layer mostly unshipped, presence layer real): break down by milestone:
  - **M6.1**: NPC schema extension (`services[]` + `price_modifier` + `mentor{}` + `role_archetype` fields) + `content/role_archetypes.json` (12 archetypes plus Quest Giver function-overlay + Shipwright) + `npc_stat_blocks` and `role_archetypes` migrations + pure function `create_npc_from_archetype` + migrate 14 NPCs in `content/npcs.json` to expanded schema + reconcile NPCStatBlock-from-CreatureStatBlock inheritance (Phase 7 dep — inline vs wait).
  - **M6.2**: `settlement_tier` and `personality` fields on Location + `content/settlement_templates.json` (4 active tiers × 17 roles × 8 personality traits) + `settlement_templates` migration + rules engine `generate_settlement_npcs` + `instantiate_npc_from_template` + agent tool `get_settlement_npc_population` + 4 hostile encounter templates (Bandit Ambush / Ashmark Patrol / Cult Cell / Hollow-Corrupted Settlement) in `content/encounter_templates.json` + faction-rep encounter-selection gating.
  - **M6.3**: mentor-variant registry (Warrior 16 + Rogue 6 + Guardian/Skirmisher/Spy/Bard/Diplomat representative variants) + `content/mentor_variants.json` + `mentor_registry` migration + `mentor{}` field on NPC schema (M6.1 dep) + `culture: str` field on mentor schema (spec L390, NEW vs milestone deliverables list) + `variant_id` dimension on `training_activities.data JSONB` (or typed column) + pure function `check_mentor_requirements` + agent tools `check_mentor_requirements` + `enroll_mentor_training` + 21+ mentor NPCs seeded in `content/npcs.json` + M2.5 ability symbols (compound dep — Cleaving Blow / Precision Strike / etc. must ship via M2.5 first).
  - **M6.4**: typed ability buckets on companion stat block (attacks/passives/actives/reactions; either extend NPC schema or split `Companion` interface) + 6 missing Kael abilities (Shield Bash + Protective Instinct + Veteran's Resilience + Hold the Line + Second Wind + Intercept) + full profiles for Lira/Tam/Sable + pure functions `scale_companion_stats_to_player_level` (75% HP) + `query_companion_relationship` + named relationship-tier enum + narrative-gate registry + `companions` + `companion_relationships` migrations + `content/companions.json` + companion ability execution in `apps/agent/combat_turn.py` + Sable non-verbal TTS handling.
- **Promote CompanionState presence layer or split as M6.5** — `apps/agent/session_data.py:15-24` ships id/is_present/is_conscious/emotional_state/relationship_tier/session_memories/last_speech_time; `companion_idle.py` ships LLM idle speech; 4 companion narration shims at `apps/agent/activity_templates.py:31-78`. Beyond M6.4's enumerated deliverables — promote to M6.4 or create M6.5 Companion Presence Layer.
- **Document errand-bonus relationship_tier coupling** at `apps/agent/async_rules.py:143-147` — out-of-combat coupling between `relationship_tier` and errand success not in M6.4 deliverables; document or move to a separate mechanic.
- **Reconcile spec/milestone divergences in 06_npcs.md** (capstone choices): Quest Giver function-overlay vs 13th archetype; Shipwright (13th spec archetype not in milestone's 12); Hamlet role-count divergence (milestone overcounts); Capital tier aspirational status; Guardian/Skirmisher/Spy/Bard 1-vs-2 mentor target; Diplomat archetype NEW; `culture` field NEW; Warrior mentor count (milestone "8+" vs spec 16); naming choices (`tier` vs `npc_tier`, `age` vs `age_range`).
- **Rename or alias `scholar_emris` ↔ `seeker_emris`** when M6.3 lands — `content/npcs.json` ships `scholar_emris` (Aelindran scholar) which matches spec L505 "Seeker-Agent Emris" Rogue L8 mentor. Same character per role.
- **Rename or coexist `hollow_patrol_greyvale` with new Ashmark Patrol** — shipped encounter is Hollow-themed; spec's Ashmark Patrol is humanoid-faction. M6.2 should add Ashmark Patrol as a new template.
- **Decide `region_type` vs `settlement_tier` orthogonality** — `content/locations.json` already uses `region_type` ∈ {city, wilderness, dungeon}; M6.2 must add `settlement_tier` as parallel axis without collapsing.

## Sprint-006 follow-up candidates

Phase 9 capstone work (largest single phase audited; 326 acceptance items across 7 spec docs, ~91% NOT_SHIPPED — see Sprint-006 findings section for the per-file table). Break down by milestone:

- **M9.1 + M9.2**: currency model (cp/sp/gc enum + `convert_currency`) + 14 canonical price tables + 11 NPC services + 4 workspaces + 3 commission tiers + 4 repair tiers + 5 mentor fee bands + 4 Hollow material tiers + `calculate_price` pure function (5-modifier composition with 0.5×–3.0× clamp) + `Npc.disposition_modifiers` field-rename/extend decision + agent tool `get_merchant_price`. Diplomat starting_gold reconciliation (25 vs 15).
- **M9.3**: tier classification on quests + `validate_quest_reward` + wealth simulation + `content/quests.json` reward calibration.
- **M9.4 Loot-side Economy (new milestone, promoted from sprint-003 decision)**: `calculate_currency_drop` + role-keyed material sell tables + Boss-bonus loot framework + tier×biome currency yield matrix. Depends on Phase 4 M4.7 + Phase 7 M7.1.
- **M9.5 Faction Reputation Pricing (new milestone)**: `ReputationTier.price_modifier` schema extension + `compute_faction_modifier` + `player_reputation` reads/writes + 5 grant + 5 loss reputation-action handlers + caps/cooldowns + service-refusal gating + faction-tier-gated inventory + 5 narration templates. **Faction content reconciliation: backfill Thornwatch + Merchant Guild + Keldaran content, OR rewrite spec to use shipped faction ids.**
- **M9.6 Merchant Inventory & Restock (new milestone)**: 3-tier stock model + 7 inventory pools restructured + `Location.size` + `Location.personality` schema + 5×6 settlement size×personality modifier matrix + `merchant_state` table (Redis + PG) + `daily_restock_at_dawn` + `attempt_purchase` + `attempt_sale` + buyback limits + consignment (Friendly+) + traveling merchant entity type + 6 narration templates. Pool/Npc binding backfill required.
- **M9.7 Supply & Demand Engine (new milestone)**: 11-tag economic taxonomy on Item + 3-phase event lifecycle + 15 standard events in `content/events.json` with `type: "economic"` + multiplicative stacking with 0.5×–3.0× clamp + `compute_item_price` + `compute_recovery_multipliers` + `economy_simulation_tick` + Redis price cache (60s TTL, region-keyed) + 4 DM narration templates.
- **M9.8 Gold Sink Ledger (new milestone)**: `sink_event_log` table + 8-category constants + `player.gold` mutation surface (`add_gold` / `consume_gold` / `attempt_charge`) + `consume_item` agent tool + `apply_rest(lodging_quality)` extension + 5 gap-analysis additions (companion gear, bribery, travel tolls with free-alternative constraint, NPC gifts with `appreciated_gifts` field; property deferred Phase 2+) + magnitude analysis aggregator.
- **M9.9 Inflation Targets & Controls (new milestone, Phase 1 portion)**: `faucet_event_log` table parallel to sink_event_log + 8 faucet categories + faucet emission wired into shipped surfaces (quest reward / inventory / currency drop) + 8-band wealth-by-level curve constants + 5 aggregate metrics + per-session balance tracker + `evaluate_economic_state` heartbeat consideration on patron system (god-whisper substrate BUILT, trigger NOT_SHIPPED) + 1-2 seasonal events as POC. Aelora/Aelindra reconciliation.
- **M9.10 P2P Trade Infrastructure (new milestone, Phase 2+; Phase 1 portion only)**: typed `provenance: ProvenanceEvent[]` field on Item (or sibling `item_history` table) + per-instance item UUID + `atomic_p2p_transfer` primitive (asyncpg conn substrate BUILT) + `Location.settlement_id` schema + same_settlement query + P2P transfer event type in unified event log.

Cross-cutting (lands across multiple M9.x):
- **Add per-event logging tables (`sink_event_log` + `faucet_event_log`) before any M9.x can ship usable telemetry** — the spec's faucet/sink balance equation has only the faucet half today (quest_tools.py reward processing). Both tables are prerequisites for M9.7 + M9.8 + M9.9.
- **Decide between extending `Npc.disposition_modifiers` vs adding a sibling `price_disposition_modifiers` field** — affects M9.2 and M9.5 simultaneously.
- **Decide between `Location.settlement_id: string` vs typed `Settlement` entity** — affects M9.6 and M9.10. Heavier `Settlement` entity supports M9.6 size+personality directly but adds a new content layer.
- **Reconcile content/spec faction roster** (Thornwatch + Merchant Guild + Keldaran missing) — affects M9.5 + M9.9 (Forge Day seasonal event has no cultural backing).

## Method

Per execution_plan.json (§Milestone 1 for sprint-001; §Milestone 2 for sprint-002; §Milestone 3 for sprint-003): for items with action verbs (add/implement/create), grep for the named symbol or file in `apps/agent/`, `apps/server/`, `packages/shared/src/entities/`, `content/`. For doc items, confirm the referenced doc/section exists and reflects the change. For spec sections without a milestone item, mark NEW with rationale. Output: table per phase with item → evidence → status (confirmed / partial / aspirational / divergent / NOT_SHIPPED).
