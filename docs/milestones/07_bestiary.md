# Phase 7: Bestiary & Encounters

> Source doc: `docs/game_mechanics/game_mechanics_bestiary.md`

Defines the full creature catalog, from stat block schema through regional creatures, Hollow special mechanics, and the encounter builder. Provides the DM agent with a complete library of adversaries and the tools to assemble balanced encounters.

---

### Milestone 7.1 — Creature Stat Block Schema

**Goal:** Define the universal creature stat block template used by all 50+ creatures, with tier-based organization and full mechanical detail including Hollow-specific extensions.

**Inputs:** Phase 1 (Core Systems — attribute model, proficiency tiers), existing basic creature data.

**Deliverables:**
- Universal creature stat block schema: id, name, category (hollow, beast, humanoid, construct, undead, elemental), tier, description, level, hp, ac, speed, attributes (STR/DEX/CON/INT/WIS/CHA), save_proficiencies, attacks[], multiattack, passives[], actives[], reactions[]
- Hollow-specific nested schema: class, corruption_aura, resonance_on_death, veil_effect, vulnerable_to
- Behavior fields: aggression pattern, retreat threshold, group tactics
- Narration fields: appearance_cue, combat_cue, death_cue (audio-first descriptions for DM)
- Audio fields: ambient_sound, attack_sound, death_sound
- Loot schema: guaranteed[], chance[] (item, probability, quantity), hollow_residue_flag
- XP reward per creature
- Tier system constants: Tier 1 (player L1-4), Tier 2 (L5-8), Tier 3 (L9-13), Tier 4 (L14-20)
- DB migration: `creatures` table with full stat block schema and JSONB fields for nested data
- Validation: `validate_creature_stat_block(creature)` ensuring all required fields and internal consistency

**Acceptance criteria:**
- [ ] Schema supports all 6 creature categories with shared base fields
- [ ] Hollow-specific nested fields are optional and only validated when category is "hollow"
- [ ] All attack entries include name, attribute, damage_dice, damage_type, range, and optional effects
- [ ] Tier system correctly maps tiers 1-4 to player level ranges
- [ ] Narration fields provide audio-first cues (sound/smell before sight)
- [ ] Loot schema supports both guaranteed and probabilistic drops
- [ ] `validate_creature_stat_block` rejects invalid entries with specific error messages
- [ ] DB migration runs cleanly with proper indexes on category, tier, and name
- [ ] Tests cover validation for all 6 categories including Hollow edge cases

**Key references:**
- *Game Mechanics Bestiary — Creature Stat Block Template*
- *Game Mechanics Bestiary — Tier System*
- *Game Mechanics Bestiary — Loot Schema*

---

### Milestone 7.2 — Regional Creature Catalog

**Goal:** Author all 38+ natural (non-Hollow) creatures organized by region, each with a complete stat block, behavior patterns, and narration cues, populating the bestiary the DM agent draws from.

**Inputs:** M7.1 (creature stat block schema).

**Deliverables:**
- 38+ creature entries across 6 regions, fully authored:
  - Greyvale: Grey Wolf, Wild Boar, Giant Spider, Bandit (Tier 1)
  - Thornveld: Thornveld Stalker, Corrupted Treant (Tier 1-2)
  - Drathian Steppe: Steppe Razorwing, Steppe Bison (Tier 1)
  - Keldaran Mountains: Rock Viper, Cave Wyrm, War Golem (Tier 1-3)
  - Sunward Coast & Wetlands: Saltmarsh Lurker, Tidecaller Eel (Tier 1-2)
  - Underground: Umbral Crawler, Deepstone Guardian (Tier 2-3)
- Each creature: full stat block, 1-3 attacks, behavior pattern (aggressive/defensive/pack/ambush), retreat condition, narration cues, audio hints
- Humanoid enemies (Bandit, Ashmark Soldier, Cult Acolyte) use NPC-like stat blocks with role-appropriate equipment
- Content: all creatures authored in `content/creatures.json` organized by region
- Agent tool: `query_creatures_by_region(region_id, tier_filter)` returning matching creatures
- Agent tool: `query_creature_by_id(creature_id)` returning full stat block

**Acceptance criteria:**
- [ ] All 38+ creatures have complete stat blocks passing M7.1 validation
- [ ] Every region has at least 3 creatures spanning appropriate tiers
- [ ] Greyvale creatures are Tier 1 only (starter region)
- [ ] Keldaran Mountains include Tier 3 creatures (late-game region)
- [ ] Each creature has distinct behavior pattern and retreat threshold
- [ ] Narration cues follow audio-first convention (sensory details, not visual descriptions)
- [ ] Humanoid enemies have equipment-based attacks matching their role
- [ ] `query_creatures_by_region` filters correctly by region and tier
- [ ] `query_creature_by_id` returns null/error for nonexistent IDs
- [ ] `content/creatures.json` passes schema validation for all entries
- [ ] Tests verify creature distribution across regions and tier balance

**Key references:**
- *Game Mechanics Bestiary — Regional Creatures*
- *Game Mechanics Bestiary — Creature Behavior Patterns*
- *Game Mechanics Bestiary — Humanoid Enemies*

---

### Milestone 7.3 — Hollow Creatures (Special Mechanics)

**Goal:** Implement the 9 Hollow creatures with unique combat mechanics that break standard patterns, including corruption auras, resonance interactions, and the 3 Tier 4 boss creatures with custom behavior systems.

**Inputs:** M7.1 (creature stat block schema with Hollow extensions), Phase 3 (Magic — Resonance system for resonance_on_death interaction).

**Deliverables:**
- 9 Hollow creatures with full stat blocks and special mechanics:
  - Tier 1-2 (combat troops): Shadeling, Hollowmoth, Mawling, Hollow Weaver
  - Tier 3 (mid-game bosses): Hollowed Knight, Veilrender
  - Tier 4 (endgame bosses): The Choir, The Still, The Architect
- Per Hollow creature: corruption_aura (radius, effect, DC), resonance_on_death (feeds Resonance system), veil_effect (environmental distortion), vulnerability
- Tier 4 custom combat behaviors:
  - The Choir: audio zone ambush, multi-voice attack, silence vulnerability
  - The Still: does not attack unless attacked first, massive defensive stats, reflects damage
  - The Architect: reshapes terrain mid-combat, creates/destroys cover, alters movement paths
- Rules engine: `apply_corruption_aura(creature, targets, distance)` returning corruption effects
- Rules engine: `resolve_resonance_on_death(creature, nearby_casters)` returning Resonance deltas
- Content: Hollow creatures in `content/creatures.json` with hollow-specific fields populated

**Acceptance criteria:**
- [ ] All 9 Hollow creatures have complete stat blocks with hollow nested fields populated
- [ ] Corruption aura applies correctly based on distance and target saves
- [ ] `resolve_resonance_on_death` feeds correct Resonance deltas to nearby casters
- [ ] Each Hollow creature has a distinct veil_effect and vulnerability
- [ ] The Choir has custom multi-phase audio-zone combat behavior (not standard attack loop)
- [ ] The Still has passive-until-attacked behavior with damage reflection
- [ ] The Architect has terrain manipulation abilities that alter combat grid state
- [ ] Tier 1-2 Hollow creatures function as standard combat encounters (no custom behavior needed)
- [ ] Tier 3 Hollowed Knight and Veilrender have boss-tier HP and multi-phase mechanics
- [ ] Tests cover corruption aura at various distances, resonance_on_death, and all 3 Tier 4 custom behaviors

**Key references:**
- *Game Mechanics Bestiary — Hollow Creatures*
- *Game Mechanics Bestiary — Corruption Aura*
- *Game Mechanics Bestiary — Resonance on Death*
- *Game Mechanics Bestiary — Tier 4 Boss Behaviors*

---

### Milestone 7.4 — Loot Tables, Harvesting & Encounter Builder

**Goal:** Implement the loot generation system with skill-gated harvesting and the encounter builder that assembles balanced combat encounters from the creature catalog.

**Inputs:** M7.1-M7.3 (creature catalog), Phase 1 (Core — skill tiers for harvesting gates), Phase 5 (Crafting — for material-to-recipe pipeline integration).

**Deliverables:**
- Loot generation: `generate_loot(creature, player_skills)` returning guaranteed drops plus probabilistic rolls
- Skill-gated harvesting tiers:
  - Survival:Trained — basic materials (pelts, bones, common herbs)
  - Crafting:Expert — refined materials (sinew, treated hide, alchemical reagents)
  - Arcana:Expert — magical components (essence, resonance shards, enchanted fragments)
- Hollow loot tainting: all Hollow creature drops flagged as tainted by default
- Purification paths: Clerics use Dispel Corruption (immediate), Artificers use async purification activity
- Encounter builder: `build_encounter(tier, combatant_count, environment)` returning creature selection with scaling
- Solo player HP math: encounters balanced for 1 player + companion at 75% effectiveness
- Environment modifiers: terrain type affects creature selection and combat difficulty
- Encounters tuned for 3-5 round resolution at expected player power
- Agent tools: `resolve_harvesting(creature_id, player_skills)` returning available materials, `generate_encounter(region, tier, difficulty)` returning encounter specification

**Acceptance criteria:**
- [ ] `generate_loot` returns guaranteed drops always and probabilistic drops at correct rates
- [ ] Harvesting requires correct skill tier: Survival:Trained, Crafting:Expert, Arcana:Expert
- [ ] Player without required skill tier gets no harvesting option (not a failed roll — gated out entirely)
- [ ] All Hollow creature loot is flagged tainted; non-Hollow loot is not
- [ ] Purification via Dispel Corruption clears taint flag; async purification tracks activity timer
- [ ] `build_encounter` selects creatures matching requested tier and scales to combatant count
- [ ] Solo encounters assume 1 player + 1 companion at 75% HP effectiveness
- [ ] Environment modifiers adjust creature selection (e.g., no aquatic creatures in mountains)
- [ ] Generated encounters resolve in 3-5 rounds given expected player damage output
- [ ] Loot materials link to Phase 5 crafting recipes where applicable
- [ ] Tests cover loot generation for all creature categories, harvesting skill gates, encounter scaling, and environment filtering

**Key references:**
- *Game Mechanics Bestiary — Loot Tables*
- *Game Mechanics Bestiary — Harvesting System*
- *Game Mechanics Bestiary — Encounter Builder*
- *Game Mechanics Crafting — Material Sources (Phase 5 link)*
