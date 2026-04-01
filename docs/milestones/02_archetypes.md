# Phase 2: Archetypes & Character Systems

> Source doc: `docs/game_mechanics/game_mechanics_archetypes.md`

Deepens character identity through 16 archetypes, ability acquisition, specialization progression, spell learning, and mentor-based technique training. Depends on Phase 1 (Core Systems).

---

### Milestone 2.1 — Archetype Chassis

**Goal:** Define the 16 archetype profiles so that character creation and leveling can reference a canonical set of HP, proficiencies, saves, resources, and starting skills for each archetype.

**Inputs:** Phase 1 (Core Systems), existing `rules_engine.py`.

**Deliverables:**
- `archetypes` DB table with columns for HP category, armor proficiencies, weapon proficiencies, save proficiencies, resource type, and starting skill proficiencies
- Content seed file `content/archetypes.json` with all 16 archetype entries
- Migration to create and seed the `archetypes` table
- Pure function `get_archetype_chassis(archetype_id)` in the rules engine returning the full chassis definition
- HP computation helpers: hit die by category (Martial 12/5, Primal-Divine 10/4, Arcane-Shadow-Support 8/3)

**Acceptance criteria:**
- [ ] 16 archetypes exist in the DB after seeding: Warrior, Guardian, Skirmisher, Mage, Artificer, Seeker, Druid, Beastcaller, Warden, Cleric, Paladin, Bard, Diplomat, Rogue, Spy, Oracle
- [ ] Each archetype record specifies HP category, armor proficiencies, weapon proficiencies, save proficiencies, resource type (Stamina-only, Focus-only, or both), and 3-5 starting skill proficiencies
- [ ] `get_archetype_chassis()` returns the correct chassis for each archetype (unit tests for all 16)
- [ ] HP at level 1 and per-level HP gain match the category formula for each archetype
- [ ] Resource type assignment is correct: martial archetypes get Stamina, arcane/divine get Focus, hybrids get both

**Key references:**
- *Game Mechanics Archetypes Doc — Archetype Chassis*
- *Game Mechanics Archetypes Doc — HP Categories*
- *Game Mechanics Archetypes Doc — Resource Type Assignment*

---

### Milestone 2.2 — Ability System (Core & Elective)

**Goal:** Implement the ability acquisition and activation system so characters have core abilities (always available, no slot cost) and elective abilities (chosen via training, scrolls, or mentors), with resource cost validation and narration cues for the DM agent.

**Inputs:** M2.1 (Archetype Chassis), existing rules engine.

**Deliverables:**
- `archetype_abilities` DB table: ability definitions (name, ability_type core/elective/reaction, cost_type, cost_amount, effect, narration_cue, archetype_id, level_requirement)
- `character_abilities` DB table: tracking which abilities a character has learned and equipped
- Content seed for core abilities (at least 1-2 per archetype)
- Elective ability pool: L4 and L8 technique choices (pool of 4 per archetype at each level)
- Reaction ability support: interrupt-triggered abilities tied to combat windows
- Agent tool `request_ability_activation` — validates resource cost, applies effect, returns narration cue
- Ability swap logic: elective techniques swappable on long rest
- Acquisition paths: Training (async), scrolls (found items), mentors (NPC training)

**Acceptance criteria:**
- [ ] Every archetype has at least one core ability seeded in the DB
- [ ] `request_ability_activation` deducts the correct Stamina or Focus cost and rejects activation when resources are insufficient
- [ ] Elective abilities at L4 and L8 present exactly 4 choices per archetype
- [ ] Characters can swap elective techniques on long rest without losing the technique
- [ ] Reaction abilities can only trigger during their defined combat window
- [ ] `request_ability_activation` returns a narration cue string for the DM agent to voice
- [ ] Unit tests cover core activation, elective activation, insufficient resources, and reaction timing

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
- Content seed for milestone abilities across all 16 archetypes
- Specialization fork data at L5: each archetype offers 2 specialization paths (e.g., Warrior picks Battle Master or Berserker)
- Agent tool `resolve_milestone` — grants milestone abilities, triggers specialization choice at L5
- Client: leveling screen with specialization choice UI at L5
- Auto-grant logic for L10, L15, L20 milestones (no player choice, abilities granted automatically)

**Acceptance criteria:**
- [ ] Each archetype has milestone entries at levels 5, 10, 15, and 20
- [ ] `resolve_milestone` at L5 presents exactly 2 specialization options and requires a player choice before granting abilities
- [ ] `resolve_milestone` at L10, L15, and L20 auto-grants abilities without requiring player input
- [ ] L10 grants Extra Attack for martial archetypes
- [ ] L20 grants a capstone ability and legendary companion unlock
- [ ] Specialization choice at L5 is persisted and cannot be changed after selection
- [ ] Client displays specialization choice UI when L5 milestone triggers
- [ ] Unit tests verify milestone grants at each tier for at least 3 different archetypes

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
- [ ] Core spells are auto-assigned at character creation and always show as prepared
- [ ] Training track respects tier-based cycle durations and advances progress each async cycle
- [ ] Midpoint decision during training modifies the learned spell's bonus variant
- [ ] `learn_spell_from_scroll` adds spell to known pool and marks acquisition track as "discovery"
- [ ] `prepare_spells` enforces preparation limits and archetype restrictions (Druid terrain, Paladin tier cap)
- [ ] Spell tier unlock gates prevent learning spells above the character's level allowance
- [ ] Unit tests cover all three acquisition tracks, preparation rules, and tier gating

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
- [ ] `mentor_variants` table stores variant overrides (cost, effect) linked to a base ability and NPC mentor
- [ ] Training loop tracks session count and unlocks the variant only after required sessions complete (2-3 sessions)
- [ ] Unlocked variant replaces or supplements the base technique at the player's choice
- [ ] Each variant has a cultural attribution string for DM narration
- [ ] Variant cost and effect overrides apply correctly when the variant ability is activated
- [ ] Training cannot begin without a valid mentor NPC relationship (depends on Phase 6 NPC data)
- [ ] Unit tests cover training progress, variant unlock, and cost/effect override application

**Key references:**
- *Game Mechanics Archetypes Doc — Martial Mentor System*
- *Game Mechanics Archetypes Doc — Style Variants*
- *Game Mechanics Archetypes Doc — Cultural Attribution*
