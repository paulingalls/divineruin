# Phase 2: Archetypes & Character Systems

> Source doc: `docs/game_mechanics/game_mechanics_archetypes.md`

Deepens character identity through 18 archetypes, ability acquisition, specialization progression, spell learning, and mentor-based technique training. Depends on Phase 1 (Core Systems).

---

## Audit Status (Sprint-002)

Sprint-002 reconciled this milestone against `game_mechanics_archetypes.md` (1357L) and shipped code. **Full audit:** `docs/milestones/audit/phase-2-archetypes.md` <!-- see audit/phase-2-archetypes.md -->.

### Coverage matrix

| Milestone | Confirmed | Partial | Aspirational | Divergent |
| --- | --- | --- | --- | --- |
| M2.1 — Archetype Chassis | 1 (HP scaling + creation classes) | 1 (chassis scattered across 2 modules) | 3 (DB table, content seed, `get_archetype_chassis`) | 0 |
| M2.2 — Ability System | 0 | 1 (L4/L8 milestone markers in `LEVEL_PROGRESSION`) | 7 (both DB tables, content seed, electives, reactions, agent tool, swap logic) | 0 |
| M2.3 — Specialization & Milestones | 1 (L5 fork flag + narrations) | 1 (narrative-only Extra Attack / capstone) | 4 (DB table, content seed, `resolve_milestone`, mobile UI) | 0 (L4/L5 fork wording settled by sprint-008) |
| M2.4 — Spell Acquisition | 0 | 1 (training activity types) | 8 (both DB tables, core spells, scroll/mentor/discovery, prep rules, tier gates, 2 tools) | 1 (durations are seconds, not "cycles") |
| M2.5 — Martial Mentor System | 0 | 1 (generic state machine + 2 mentor NPC stubs) | 6 (mentor_variants table, variant data, attribution, multi-session loop, agent integration, tests) | 0 |

### Material gaps

**STATUS UPDATE (post Sprint-002): the Sprint-002 "ZERO criteria met" snapshot below is now stale.** M2.1 shipped (sprint-016) and the ability/milestone/spell/mentor systems subsequently shipped under their own execution-plan numbering (M2.2 as "M4 ability", M2.3 as "M4 milestone", M2.4 as "M8 spell acquisition", M2.5 as "M9 martial mentor" / M6.3 mentor gating), each with a real-DB acceptance capstone. 30/34 acceptance criteria are now checked; the 4 that remain unchecked are genuinely deferred (see per-milestone status notes). The Sprint-002 spec-vs-code findings below are retained for history: <!-- see audit/phase-2-archetypes.md -->:

- **M2.1**: DB table, `content/archetypes.json`, `get_archetype_chassis()` are aspirational. 18 archetypes live in `apps/agent/{hp_scaling,rules_engine,creation_classes}.py` (Sprint-001 finding, still true). Stale `ClassData.hit_die` field diverges from `ARCHETYPE_HP_CONFIG` — capstone recommends dropping or documenting as cosmetic. <!-- see audit/phase-2-archetypes.md -->
- **M2.2**: Entire ability system aspirational. Only L4/L8 milestone *markers* exist. Sprint-001 carryover: `validateSlotAvailability` Artificer dead-code exception needs reconciliation (wire or remove). <!-- see audit/phase-2-archetypes.md -->
- **M2.3**: L5 `specialization_fork=True` flag + narration confirmed; per-archetype option pairs (Battle Master / Berserker etc.), `resolve_milestone` tool, and mobile UI all aspirational. L4/L5 fork wording was settled by sprint-008 in `01_core_systems.md §M1.4` — L4 emits an `elective_techniques` milestone, L5 is the specialization fork; the spec was reworded to L5-only. <!-- see audit/phase-2-archetypes.md -->
- **M2.4**: Spell system aspirational. Training infra exists but uses real-time seconds, not the spec's discrete "cycles". `spell_minor` tier missing from `content/training_activity_types.json`. **NEW deliverable suggested**: per-archetype elective spell progression tables (slot+cantrip counts per level for all 13 caster/hybrid archetypes) are unimplemented and not currently named in M2.4 acceptance. <!-- see audit/phase-2-archetypes.md -->
- **M2.5**: Mentor system aspirational. 2 mentor NPC personality stubs + generic training state machine exist but are not bound to abilities or variants. **NEW deliverables suggested**: per-variant character-sheet attribution display (spec L1339-1347); "one variant per technique, swap requires re-training" rule (spec L1354). <!-- see audit/phase-2-archetypes.md -->

### Cross-doc dependencies

- **M2.4 spell acquisition ↔ Phase 3 Magic** — `character_spells.spell_id` foreign key needs the Arcane/Divine/Primal catalogs from `game_mechanics_magic.md`. See `audit/phase-3-magic.md`.
- **M2.3 L5 specialization options ↔ Phase 8 Patrons** — Cleric Domain Specialization (archetypes spec L265) and Paladin Oath Specialization (L817) are patron-driven; Oracle's "dual allegiance" (L833) is patron-system territory. See `audit/phase-8-patrons.md`.
- **M2.5 mentors ↔ Phase 6 NPCs** — "Valid mentor NPC relationship" precondition depends on Phase 6 disposition system. Cultural attribution (Drathian Clans / Keldaran Holds / Thornwardens / Tidecallers — spec L1313) depends on Phase 5/6 region+culture content.
- **M2.2 reaction abilities ↔ Combat phase** — Combat-window enforcement shipped in M2.2 story-002 (`combat_phase.validate_reaction_activation` + the `ability_tools` activation gate), not in Phase 4.
- **M2.5 ↔ Async activity system** — `apps/server/src/training_state_machine.ts` is the extension point for the multi-session mentor loop.

---

### Milestone 2.1 — Archetype Chassis

**Goal:** Define the 18 archetype profiles so that character creation and leveling can reference a canonical set of HP, proficiencies, saves, resources, and starting skills for each archetype.

**Inputs:** Phase 1 (Core Systems), existing `rules_engine.py`.

**Deliverables:**
- `archetypes` DB table with columns for HP category, armor proficiencies, weapon proficiencies, save proficiencies, resource type, and starting skill proficiencies
- Content seed file `content/archetypes.json` with all 18 archetype entries
- Migration to create and seed the `archetypes` table
- Pure function `get_archetype_chassis(archetype_id)` in the rules engine returning the full chassis definition
- HP computation helpers: hit die by category (Martial 12/5, Primal-Divine 10/4, Arcane-Shadow-Support 8/3)

**Acceptance criteria:**
- [x] 18 archetypes exist in the DB after seeding: Warrior, Guardian, Skirmisher, Mage, Artificer, Seeker, Druid, Beastcaller, Warden, Cleric, Paladin, Oracle, Rogue, Spy, Whisper, Bard, Diplomat, Marshal
- [x] Each archetype record specifies HP category, armor proficiencies, weapon proficiencies, save proficiencies, resource type (Stamina-only, Focus-only, or both), and 3-5 starting skill proficiencies
- [x] `get_archetype_chassis()` returns the correct chassis for each archetype (unit tests for all 18)
- [x] HP at level 1 and per-level HP gain match the category formula for each archetype
- [x] Resource type assignment is correct: martial archetypes get Stamina, arcane/divine get Focus, hybrids get both

**Key references:**
- *Game Mechanics Archetypes Doc — Archetype Chassis*
- *Game Mechanics Archetypes Doc — HP Categories*
- *Game Mechanics Archetypes Doc — Resource Type Assignment*

### CAPSTONE — M2.1 shipped (sprint-016, story-005)

<!-- capstone-footer: grep "CAPSTONE — M2.1" -->

**Status: SHIPPED.** All 5 M2.1 acceptance criteria above are met end-to-end.

- **Story chain:** story-001 (`content/archetypes.json` SSOT for all 18 chassis + migration 029 + seed) → 002 (Python `archetypes.py` loader; folded `calculate_max_hp`/`calculate_max_pools` onto `get_archetype_chassis`, deleting `ARCHETYPE_HP_CONFIG`/`ARCHETYPE_RESOURCE_CONFIG`) → 003 (TS `archetypes.ts` loader + shared `Archetype` entity type) → 004 (reconciled `creation_classes`: dropped stale `ClassData.hit_die`, routed saves/skills/HP through the chassis SSOT) → **005 (this capstone)**.
- **Capstone proof:** `apps/agent/tests/acceptance/test_archetype_chassis.py` proves the chassis composes end-to-end against one seeded Postgres testcontainer across both surfaces — message_event (Python `load_archetypes` → all 18 resolve via `get_archetype_chassis`, `calculate_max_hp`/`calculate_max_pools` match the spec-anchored `EXPECTED_HP`/`EXPECTED_RESOURCE`) and http_websocket (a spawned Bun `src/index.ts` whose startup `loadArchetypes()` resolving all 18 from the same DB without throwing is the server chassis-load proof). 4/4 capstone tests green via `bun run test:acceptance`.
- **Also landed in story-005 (adopted spec re-read Try):** a pre-capstone conformance pass against `game_mechanics_archetypes.md` corrected two divergences the story-001 legacy-constant fold introduced — Oracle HP retiered 10/4→8/3 arcane_shadow (decision `oracle-hp-spec-fix`), and all 18 `starting_skills` rewritten to the spec's fixed per-archetype grants, restoring signature skills (Crafting/Performance) the old pool model dropped (decision `starting-skills-spec-conformance`).
- **Verified-at:** content/anchor fix `0a174ff`, capstone E2E `b8b3030`; final close SHA recorded at sprint-close.

**Open follow-ups:**
- No server archetype REST endpoint yet — the http_websocket surface proves the server boots + loads all 18; a REST surface lands when a consumer needs it (decision `archetype-rest-surface-deferred`).
- `get_skill_proficiencies` choose-N branch is now vestigial (every archetype has `num_choices == len(options)`); either delete it or make the partial-choice mismatch fail loud (debt `30f87f292585`).
- Acceptance test imports the `EXPECTED_HP`/`EXPECTED_RESOURCE` anchors from sibling unit-test modules; the cleaner home is a shared non-test module (concern `a8a4ba42bebd`).

---

### Milestone 2.2 — Ability System (Core & Elective)

**Goal:** Implement the ability acquisition and activation system so characters have core abilities (always available, no slot cost) and elective abilities (chosen via training, scrolls, or mentors), with resource cost validation and narration cues for the DM agent.

**Inputs:** M2.1 (Archetype Chassis), existing rules engine.

**Deliverables:**
- `archetype_abilities` DB table: ability definitions (name, ability_type core/elective/reaction, cost `{stamina, focus, scaling}`, effect, narration_cue, archetype_id, level_requirement)
- `character_abilities` DB table: tracking which abilities a character has learned and equipped
- Content seed for core abilities (at least 1-2 per archetype)
- Elective ability pool: L4 and L8 technique choices (pool of 4 per archetype at each level)
- Reaction ability support: interrupt-triggered abilities tied to combat windows
- Agent tool `request_ability_activation` — validates resource cost, applies effect, returns narration cue
- Ability swap logic: elective techniques swappable on long rest
- Acquisition paths: Training (async), scrolls (found items), mentors (NPC training)

**Acceptance criteria:**
- [x] Every archetype has at least one core ability seeded in the DB
- [x] `request_ability_activation` deducts the correct Stamina or Focus cost and rejects activation when resources are insufficient
- [x] Elective abilities at L4 and L8 present exactly 4 choices per archetype
- [x] Characters can swap elective techniques on long rest without losing the technique
- [x] Reaction abilities can only trigger during their defined combat window
- [x] `request_ability_activation` returns a narration cue string for the DM agent to voice
- [x] Unit tests cover core activation, elective activation, insufficient resources, and reaction timing

> **Status (shipped):** Ability catalog, activation/cost-rejection, L4/L8 elective pools, long-rest swap, and narration cues are delivered and tested (unit tests + `tests/acceptance/test_story_005_m22_ability_capstone.py`). AC5/AC7's reaction leg landed in story-002: a REACTION is declared at Beat 1 with its catalog window as `trigger`, and `activate` refuses it unless the combat is at the RESOLUTION beat, the declaration is that exact ability, its trigger equals the catalog `window`, and the round's one reaction is unspent (`combat_phase.validate_reaction_activation`). **Scope caveat:** the gate is scoped to combat — a session with no `combat_state` activates a reaction UNGATED, which keeps the four socially-worded reactions (`spy_plausible_deniability`, `diplomat_objection`, `whisper_implant_doubt`, `marshal_countermand`) usable outside a fight. There is no reaction budget outside combat, so those four are still unmetered.

**Key references:**
- *Game Mechanics Archetypes Doc — Core Abilities*
- *Game Mechanics Archetypes Doc — Elective Abilities*
- *Game Mechanics Archetypes Doc — Reaction Abilities*

---

### Milestone 2.3 — Specialization & Milestone Progression

**Goal:** Implement the four-tier milestone progression (Identity, Power, Mastery, Legend) so characters gain automatic abilities at key levels and make meaningful specialization choices at L5.

**Inputs:** M2.2 (Ability System).

**Deliverables:**
- `archetype_milestones` DB table: milestone_tier (Identity/Power/Mastery/Legend), level (5/10/15/20), archetype_id, granted_abilities, specialization_options (for L5)
- Content seed for milestone abilities across all 18 archetypes
- Specialization fork data at L5: each archetype offers 2 specialization paths (e.g., Warrior picks Battle Master or Berserker)
- Agent tool `resolve_milestone` — grants milestone abilities, triggers specialization choice at L5
- Client: leveling screen with specialization choice UI at L5
- Auto-grant logic for L10, L15, L20 milestones (no player choice, abilities granted automatically)

**Acceptance criteria:**
- [x] Each archetype has milestone entries at levels 5, 10, 15, and 20
- [x] `resolve_milestone` at L5 presents exactly 2 specialization options and requires a player choice before granting abilities
- [x] `resolve_milestone` at L10, L15, and L20 auto-grants abilities without requiring player input
- [x] L10 grants Extra Attack for martial archetypes
- [ ] L20 grants a capstone ability and legendary companion unlock
- [x] Specialization choice at L5 is persisted and cannot be changed after selection
- [x] Client displays specialization choice UI when L5 milestone triggers
- [x] Unit tests verify milestone grants at each tier for at least 3 different archetypes

> **Status (mostly shipped):** Milestone entries at 5/10/15/20, the L5 specialization fork (exactly 2 options for non-patron archetypes, surfaced as a `SPECIALIZATION_CHOICE` event and persisted immutably by the `select` verb — `resolve_milestone` was superseded by the `award_xp` auto-grant chokepoint + `select`; M28 story-003 then removed the `award_xp` tool itself, leaving that chokepoint as the `_award_xp_core` Resolve), L10 auto-grant Extra Attack, and the mobile `specialization-overlay.tsx` are delivered and tested (unit tests + `tests/acceptance/test_milestone_progression.py`, mobile `specialization-choice.test.ts`). AC5's "legendary companion unlock" half is not implemented — L20 content grants only a capstone ability — left unchecked.

**Key references:**
- *Game Mechanics Archetypes Doc — Milestone Progression*
- *Game Mechanics Archetypes Doc — Specialization Forks*
- *Game Mechanics Archetypes Doc — Capstone Abilities*

---

### Milestone 2.4 — Spell Acquisition (3 Tracks)

**Goal:** Implement the three spell acquisition tracks (Core, Training, Discovery) and the spell preparation system so casters can learn, study, and prepare spells according to their archetype rules.

**Inputs:** M2.2 (Ability System), existing async activity system.

**Deliverables:**
- `character_spells` DB table: character_id, spell_id, acquisition_track (core/training/discovery), is_prepared, date_learned
- `spell_learning_progress` DB table: character_id, spell_id, cycles_completed, cycles_required, midpoint_decision, started_at
- Core spell assignment: fixed spells per archetype, always prepared, no elective slot cost
- Training track: spell-study cycle in async loop with tier-based durations (cantrip 1 cycle, Minor 2, Standard 3, Major 5, Supreme 8)
- Midpoint decision support: micro-bonus variation choices during training
- Discovery track: learn from scrolls and NPC mentors (including mentor-exclusive variants)
- Spell preparation: prepare from known pool on long rest; Druid restriction (natural terrain only), Paladin restriction (capped at Major tier)
- Spell tier unlock by level: Cantrip L1, Minor L1, Standard L4, Major L7, Supreme L13
- Agent tools: `learn_spell_from_scroll`, `prepare_spells`

**Acceptance criteria:**
- [x] Core spells are auto-assigned at character creation and always show as prepared
- [x] Training track respects tier-based cycle durations and advances progress each async cycle
- [x] Midpoint decision during training modifies the learned spell's bonus variant
- [x] `learn_spell_from_scroll` adds spell to known pool and marks acquisition track as "discovery"
- [x] `prepare_spells` enforces preparation limits and archetype restrictions (Druid terrain, Paladin tier cap)
- [x] Spell tier unlock gates prevent learning spells above the character's level allowance
- [x] Unit tests cover all three acquisition tracks, preparation rules, and tier gating

> **Status (shipped):** All 7 criteria delivered and tested (unit tests + `tests/acceptance/test_spell_acquisition.py`). The primal terrain gate and the Major-tier cap are enforced via the `(archetype, tier, level)` matrix in `spell_preparation`/`is_spell_tier_unlocked`.

**Key references:**
- *Game Mechanics Archetypes Doc — Spell Acquisition Tracks*
- *Game Mechanics Archetypes Doc — Spell Preparation*
- *Game Mechanics Archetypes Doc — Spell Tier Unlocks*

---

### Milestone 2.5 — Martial Mentor System

**Goal:** Implement the mentor-based technique training system so martial characters can learn style variants of their base techniques from NPC mentors, replacing multiclassing with focused technique specialization.

**Inputs:** M2.2 (Ability System), Phase 6 (NPCs) for mentor NPC data.

**Deliverables:**
- `mentor_variants` DB table: variant_id, base_ability_id, npc_mentor_id, variant_name, cost_override, effect_override, cultural_attribution, training_sessions_required
- 2-3 session training loop implementation: progress tracking, completion check, variant unlock
- Style variant data: at least one variant per martial base technique (L4 and L8 choices)
- Example variant: Cleaving Blow base (4 Stam, hits 2 adjacent) -> Whirlwind Style variant (5 Stam, hits all in melee)
- Cultural attribution field linking variant styles to in-world cultures
- Agent integration: mentor NPC can offer training, track progress across sessions, grant variant on completion

**Acceptance criteria:**
- [x] `mentor_variants` table stores variant overrides (cost, effect) linked to a base ability and NPC mentor
- [x] Training loop tracks session count and unlocks the variant only after required sessions complete (2-3 sessions)
- [x] Unlocked variant replaces or supplements the base technique at the player's choice
- [x] Each variant has a cultural attribution string for DM narration
- [x] Variant cost and effect overrides apply correctly when the variant ability is activated
- [x] Training cannot begin without a valid mentor NPC relationship (depends on Phase 6 NPC data)
- [x] Unit tests cover training progress, variant unlock, and cost/effect override application

> **Status (shipped):** Variant catalog, the 3-cycle mentor training loop, cultural attribution, variant activation, and co-location + mentor-requirement gating are delivered and tested (unit tests + `tests/acceptance/test_mentor_variants.py`, `test_mentor_gating_e2e.py`). AC3 closed by M9 story-004 (2026-09-01): a variant no longer overrides its base. `activate` routes variant ids as a fourth namespace, so the player chooses per activation — base id for the base cost/effect, variant id for the variant's. `set_active_variant` still allows only ONE activatable variant per technique, so a second trained variant makes the first unlocked-but-unusable; supplement is between base and variant, not among variants.
>
> Not shipped: nothing surfaces a learned variant's *id* to the DM — `query_info` has no ability/variant kind and the unlock narration carries only the cultural-attribution prose — so the variant namespace is routable but not yet discoverable at the table.

**Key references:**
- *Game Mechanics Archetypes Doc — Martial Mentor System*
- *Game Mechanics Archetypes Doc — Style Variants*
- *Game Mechanics Archetypes Doc — Cultural Attribution*
