# Phase 6: NPCs & Companions

> Source doc: `docs/game_mechanics/game_mechanics_npcs.md`

Builds the NPC mechanical layer: stat block schemas, settlement population templates, mentor training registry, and companion combat profiles with relationship progression. Transforms NPCs from narrative-only entities into mechanically rich, role-differentiated game participants.

---

### Milestone 6.1 — NPC Stat Block Schema & Role Archetypes

**Goal:** Define the universal NPC schema extending creature stat blocks with social, economic, and mentor layers, plus 12 role archetypes with default profiles.

**Inputs:** Phase 1 (Core Systems — attribute model, skill tiers), existing `content/npcs.json` and NPC DB entities.

**Deliverables:**
- NPC stat block schema with fields: npc_tier (authored vs template), role, species, personality, disposition (base value, modifier list, gated knowledge thresholds), schedule, services, price_modifier, mentor data, voice_id
- 12 role archetype templates:
  - Merchant (7 subtypes: General, Weapons, Alchemist, Jeweler, Exotic, Traveling, Black Market)
  - Blacksmith, Innkeeper, Healer/Temple, Scholar, Guard, Soldier (with Ashmark variants), Assassin/Rogue, Mage, Priest, Fence, Stablemaster
- Per-archetype defaults: combat stats, services offered, inventory pool, knowledge domains, disposition baseline, special abilities
- DB migration: `npc_stat_blocks` table with full schema, `role_archetypes` template table
- Updated `content/npcs.json` with expanded schema for all existing NPCs
- Pure function: `create_npc_from_archetype(role, overrides)` returning a complete stat block

**Acceptance criteria:**
- [ ] NPC stat block schema validates all required fields including social/economic/mentor layers
- [ ] All 12 role archetypes defined with default combat stats, services, inventory pools, and knowledge domains
- [ ] Merchant subtypes have distinct inventory pools and price_modifier ranges
- [ ] Disposition supports base value, modifier list, and gated knowledge thresholds
- [ ] `create_npc_from_archetype` produces valid stat blocks for every archetype
- [ ] Existing NPCs in `content/npcs.json` migrated to expanded schema without data loss
- [ ] DB migration runs cleanly and schema matches entity definitions
- [ ] Tests cover all 12 archetypes and Merchant subtypes

**Key references:**
- *Game Mechanics NPCs — NPC Stat Block Schema*
- *Game Mechanics NPCs — Role Archetypes*
- *Game Mechanics NPCs — Disposition System*

---

### Milestone 6.2 — Settlement Templates & NPC Population

**Goal:** Implement settlement tier templates that auto-generate NPC populations scaled to location size and personality, enabling the DM agent to populate any settlement on demand.

**Inputs:** M6.1 (NPC stat block schema and role archetypes), existing location entities in DB.

**Deliverables:**
- 5 settlement tiers with NPC role distributions:
  - Hamlet: 1 innkeeper, 1 merchant, 1 healer (partial)
  - Village: 1 innkeeper, 1-2 merchants, 1 blacksmith, 1 healer
  - Town: 2 innkeepers, 3-4 merchants, 1-2 blacksmiths, 1 healer, 1 scholar, 2 guards
  - City: 5+ innkeepers, multiple of every role, faction representatives
  - Capital: full role coverage with named authored NPCs supplementing templates
- 8 settlement personality traits: Prosperous, Struggling, Military, Scholarly, Corrupt, Devout, Frontier, Refuge — each modifying NPC disposition baselines and inventory pools
- DB migration: `settlement_templates` table (tier, personality, role_distribution)
- Rules engine: `generate_settlement_npcs(location_tier, personality)` returning a list of instantiated NPC stat blocks
- Template-based generation: `instantiate_npc_from_template(role, settlement_tier, personality)` applying tier and personality modifiers
- Agent tool: `get_settlement_npc_population` for DM agent to query or generate on demand

**Acceptance criteria:**
- [ ] All 5 settlement tiers defined with correct NPC role distributions
- [ ] All 8 personality traits modify NPC disposition baselines and inventory pools
- [ ] `generate_settlement_npcs` produces correct role counts for every tier
- [ ] `instantiate_npc_from_template` applies settlement tier and personality modifiers to archetype defaults
- [ ] Generated NPCs have unique names, varied personalities within archetype constraints
- [ ] Agent tool `get_settlement_npc_population` returns valid NPC list for any location
- [ ] Settlement personality "Corrupt" increases Fence/Black Market frequency and reduces Guard disposition
- [ ] Tests cover all tier/personality combinations

**Key references:**
- *Game Mechanics NPCs — Settlement Templates*
- *Game Mechanics NPCs — NPC Population Distribution*
- *Game Mechanics NPCs — Settlement Personality Traits*

---

### Milestone 6.3 — Mentor Registry & Training

**Goal:** Build the mentor registry mapping technique variants to NPC mentors with multi-requirement training enrollment, connecting NPCs to the player ability progression system.

**Inputs:** M6.1 (NPC stat blocks with mentor data), Phase 2 M2.5 (Martial Mentor System — ability-side implementation).

**Deliverables:**
- Mentor registry data structure: technique_id maps to variant list, each variant maps to mentor NPC with training data
- Warrior technique mentors (8+ variants): Cleaving Blow, Precision Strike, Taunt, Reckless Assault (L4); War Cry, Unstoppable Charge, Whirlwind, Iron Stance (L8)
- Rogue technique mentors (5+ variants)
- Representative mentors for Guardians, Skirmishers, Bards, and Spies
- Mentor nested data per variant: technique, variant_name, variant_effect, training_cycles, requirements (disposition threshold, quest completion, gold payment, skill tier), narration_cue
- DB migration: `mentor_registry` table (technique_id, variant_id, mentor_npc_id, requirements, training_cycles)
- Rules engine: `check_mentor_requirements(player, mentor, variant)` returning pass/fail with specific unmet requirements
- Agent tools: `check_mentor_requirements` (query), `enroll_mentor_training` (mutation — starts training cycle)

**Acceptance criteria:**
- [ ] Mentor registry covers all Warrior L4 and L8 technique variants (8+ mentors)
- [ ] Rogue mentors cover 5+ technique variants
- [ ] Guardian, Skirmisher, Bard, and Spy archetypes each have at least 2 representative mentors
- [ ] `check_mentor_requirements` correctly evaluates disposition threshold, quest completion, gold, and skill tier
- [ ] `check_mentor_requirements` returns specific unmet requirements (not just pass/fail)
- [ ] `enroll_mentor_training` validates requirements before enrollment and returns error if unmet
- [ ] Training cycles are tracked per player per variant
- [ ] Mentor data links correctly to Phase 2 M2.5 ability definitions
- [ ] Tests cover requirement combinations (all met, one unmet, multiple unmet)

**Key references:**
- *Game Mechanics NPCs — Mentor Registry*
- *Game Mechanics NPCs — Training Requirements*
- *Game Mechanics Archetypes — Martial Mentor System (M2.5)*

---

### Milestone 6.4 — Companion Profiles & Scaling

**Goal:** Implement the 4 named companion archetypes with combat profiles that scale to the player, distinct tactical identities, and a relationship progression system that gates narrative content (not combat power).

**Inputs:** M6.1 (NPC stat blocks), Phase 1 (Core Systems — leveling), Phase 4 (Combat — for companion combat integration).

**Deliverables:**
- 4 companion archetypes with full combat profiles:
  - Kael (ranger/martial): melee/ranged hybrid, tactical positioning
  - Lira (healer/support): healing, buffs, low direct damage
  - Tam (rogue/shadow): stealth, burst damage, evasion
  - Sable (mage/arcane): AoE damage, crowd control, glass cannon
- Per companion: 2-4 attacks, 2-3 passives, 2-3 actives, 0-1 reactions
- HP scaling: companions scale to 75% of player HP at any level
- 5 relationship tiers: New, Warming, Trusted, Bonded, Legendary
- Relationship gates secrets and narratives (NOT combat abilities — companions fight at full capacity regardless of relationship)
- Hostile encounter templates using companions: Bandit Ambush, Ashmark Patrol, Cult Cell, Hollow-Corrupted Settlement
- DB migration: `companions` table (archetype, base_stats, ability_list, scaling_rules), `companion_relationships` table (player_id, companion_id, tier, progression_value)
- Rules engine: `scale_companion_stats_to_player_level(companion, player_level)` returning scaled stat block
- Rules engine: `query_companion_relationship(player_id, companion_id)` returning tier and available narrative gates
- Content: companion profiles in `content/companions.json`

**Acceptance criteria:**
- [ ] All 4 companions have complete combat profiles with distinct tactical identities
- [ ] Each companion has correct count of attacks (2-4), passives (2-3), actives (2-3), reactions (0-1)
- [ ] `scale_companion_stats_to_player_level` produces HP at 75% of player HP for levels 1-20
- [ ] All 5 relationship tiers defined with narrative content gates
- [ ] Relationship tier does NOT affect combat stats or ability availability
- [ ] Hostile encounter templates reference correct companion combat behaviors
- [ ] Companion stat blocks pass same validation as NPC stat blocks (shared schema base)
- [ ] Tests cover scaling at level boundaries (1, 5, 10, 15, 20) and all relationship tier transitions
- [ ] `content/companions.json` contains all 4 companions with full data

**Key references:**
- *Game Mechanics NPCs — Companion Archetypes*
- *Game Mechanics NPCs — Companion Scaling*
- *Game Mechanics NPCs — Relationship Progression*
- *Game Mechanics NPCs — Hostile Encounter Templates*
