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
- [x] NPC stat block schema validates all required fields including social/economic/mentor layers
- [x] All 12 role archetypes defined with default combat stats, services, inventory pools, and knowledge domains
- [x] Merchant subtypes have distinct inventory pools and price_modifier ranges
- [x] Disposition supports base value, modifier list, and gated knowledge thresholds
- [x] `create_npc_from_archetype` produces valid stat blocks for every archetype
- [x] Existing NPCs in `content/npcs.json` migrated to expanded schema without data loss
- [x] DB migration runs cleanly and schema matches entity definitions
- [x] Tests cover all 12 archetypes and Merchant subtypes

**Key references:**
- *Game Mechanics NPCs — NPC Stat Block Schema*
- *Game Mechanics NPCs — Role Archetypes*
- *Game Mechanics NPCs — Disposition System*

### Audit Status (Sprint-005)

<!-- see audit/phase-6-schema-archetypes.md -->

**Status: DELIVERED.** Superseded — the Sprint-005 snapshot below is stale. The mechanical archetype layer shipped: `content/role_archetypes.json` (19 archetypes: 12 base incl. Shipwright + 7 Merchant subtypes) + migration `039_role_archetypes.sql` + `apps/agent/role_archetypes.py` (`RoleArchetype` schema, `create_npc_from_archetype`, 5-tier disposition SSOT). `content/npcs.json` migrated to 17 NPCs each carrying a resolvable `role_archetype`; Merchant subtypes have distinct `inventory_pool` + `price_modifier` (1.0–1.5); `mentor{}` blocks carry culture/training_cycles/requirements. Verified by capstone `tests/acceptance/test_story_005_m6_npc_archetype_capstone.py` (both language surfaces) + green unit tests (`test_role_archetypes.py`, `test_npc_migration.py`). All 8 ACs met.

The Sprint-005 audit paragraph below is retained for history only.

| Section | BUILT | DESIGNED | NOT_SHIPPED |
| --- | --- | --- | --- |
| M6.1 — NPC Stat Block Schema & Role Archetypes (8) | 1 | 1 | 6 |

**Material gaps:**
- `content/role_archetypes.json` (or migration-seeded `role_archetypes` table) does not exist. Spec defines 12 archetypes plus Quest Giver function-overlay and Shipwright role — none seeded.
- `npc_stat_blocks` typed DB table — no migration creates it. Generic `npcs (id, data JSONB)` from migration 001 is the only NPC store.
- NPC schema missing M6.1 expansion fields (`services`, `price_modifier`, `mentor{}`, `role_archetype`). Spec L18 inherits NPCStatBlock from CreatureStatBlock which is also unshipped (Phase 7 surface).
- 14 NPCs in `content/npcs.json` have not been migrated to the expanded schema; no Tier-2 template-generated entries.
- Combat stat blocks for Guard / Soldier / Assassin / Mage / Priest / Innkeeper bouncer (Guard) all depend on CreatureStatBlock (Phase 7).

**Cross-doc deps:**
- M6.1 → Phase 7 Bestiary: NPCStatBlock inherits from CreatureStatBlock per spec L18; Phase 7's base type must land first or M6.1 inlines combat fields.
- M6.1 → Phase 3 Magic + Phase 3 Gods: Mage and Priest archetypes carry Focus pool + spell catalog (npcs.md:300-339); Healer/Temple binds to a patron god (npcs.md:151).
- M6.1 → M6.3 Mentor Registry: `mentor{}` nested field in the schema is consumed by M6.3 (`apps/agent/activity_templates.py:14-28` `TRAINING_MENTORS` carries narration data but not structured requirements).
- M6.1 → Phase 9 Economy: `price_modifier` and per-Merchant-subtype price ranges feed Phase 9's faction-rep pricing engine.

**Spec/milestone conflicts to record:**
- **Quest Giver** archetype (gm_npcs L190-206) is NEW vs milestone's 12 — spec explicitly notes "Not a standalone role." Treat as `quest_giver?: bool` flag or function overlay. Tracked in `audit/README.md` Sprint-005 capstone annotations.
- **Shipwright** archetype (gm_npcs L370-375) is NEW vs milestone's 12 — milestone undercounts by 1. Tracked in `audit/README.md` Sprint-005 capstone annotations.

See `audit/phase-6-schema-archetypes.md` for the full coverage matrix.

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
- [x] All 4 surviving settlement tiers (hamlet/village/town/city) defined with correct NPC role distributions; `keldaran_hold` normalizes to city <!-- AMENDED 2026-09-01 (decision D-1). Was "All 5 settlement tiers", which is unsatisfiable against the source spec: game_mechanics_npcs.md:556 lists Capital as "(None currently exist — the Sundering destroyed the great cities)", and its Role Distribution by Settlement Size table at :560 has only 4 columns — the spec defines NO role distribution for Capital. Building one would mean inventing content for a settlement class the lore destroyed. Shipped state is spec-aligned and deliberate: content/settlement_templates.json has the 4 tier rows; SETTLEMENT_SIZE_VALUES (location.ts:34-40) carries keldaran_hold, which is dual-natured and NOT a leftover: it is a first-class distinct size for WORKSPACE availability (game_mechanics_crafting.md:240 gives it the only Laboratory=Sometimes row — renowned forges, weaker alchemy — encoded at workspace.py:130-134 and pinned by test_workspace.py:140::test_keldaran_hold_forges_renowned_lab_limited), but City-scale for NPC ROLE COUNTS (game_mechanics_npcs.md:555 lists Keldaran holds as City examples), so settlement_generation.py:25 _TIER_ALIASES maps it to city on that axis only. Pinned by apps/agent/tests/test_settlement_generation.py:85::test_keldaran_hold_maps_to_city and test_settlement_templates.py:146 (get_settlement_tier stays fail-loud on it elsewhere). Correct-distribution half is carried by the adjacent [x] AC "generate_settlement_npcs produces correct role counts for every tier". -->
- [x] All 8 personality traits modify NPC disposition baselines and inventory pools
- [x] `generate_settlement_npcs` produces correct role counts for every tier
- [x] `instantiate_npc_from_template` applies settlement tier and personality modifiers to archetype defaults
- [x] Generated NPCs have unique names, varied personalities within archetype constraints <!-- MET 2026-09-02 (story-010): generate_settlement_roster preserves role counts while assigning settlement-unique names and distinct 2-3 trait sets from each role's content pool. Name-pool exhaustion widens into given+surname pairs, so every generated name stays speakable; a conformance test blocks any pool name that collides with an authored character. Pinned by test_settlement_generation.py::TestRoster, test_query.py::TestSettlementPopulation, and test_m62_settlement_capstone.py. -->
- [x] Agent tool `get_settlement_npc_population` returns valid NPC list for any location
- [x] Settlement personality "Corrupt" increases Fence/Black Market frequency and reduces Guard disposition
- [x] Tests cover all tier/personality combinations

**Key references:**
- *Game Mechanics NPCs — Settlement Templates*
- *Game Mechanics NPCs — NPC Population Distribution*
- *Game Mechanics NPCs — Settlement Personality Traits*

### Audit Status (Sprint-005)

<!-- see audit/phase-6-settlements.md -->

**Status: DELIVERED (capstone `test_m62_settlement_capstone.py` passes; all ACs met).** Superseded — the Sprint-005 snapshot below is stale. Shipped: `content/settlement_templates.json` (4 tiers hamlet/village/town/city + 8 settlement personalities + a generated given-name/surname pool), migration `040_settlement_templates.sql`, and `apps/agent/settlement_templates.py` / `settlement_generation.py` (counts, named rosters, and template instantiation). Per-role content pools produce distinct 2-3 trait personalities. Agent tool `query_settlement_population` surfaces counts and roster. Corrupt settlements raise fence/black-market frequency and lower guard disposition. The 4 hostile-encounter templates (bandit_ambush, ashmark_patrol, cult_cell, hollow_corrupted_settlement) ship in `content/encounter_templates.json`.

The Sprint-005 audit paragraph below is retained for history only.

| Section | BUILT | DESIGNED | NOT_SHIPPED |
| --- | --- | --- | --- |
| M6.2 — Settlement Templates & NPC Population (8) | 0 | 0 | 8 |

**Material gaps:**
- `content/settlement_templates.json` (or migration-seeded `settlement_templates` table) does not exist. Spec defines 4 active tiers × ~17 roles + 8 personality traits — none seeded.
- `settlement_tier` field on Location: neither in TS interface (`location.ts`) nor in any of 18 `content/locations.json` entries.
- `personality` field on Location: same — not in interface, not in content.
- 3 generation surfaces all 0-hit grep.
- 4 hostile encounter templates absent from content; `encounter_templates` storage table ships unused for these.
- Stat blocks for encounter composition (Bandit, Bandit Captain, Cult Fanatic, Hollowed Knight) depend on M6.1 + Phase 7 Bestiary.

**Cross-doc deps:**
- M6.2 → M6.1: `instantiate_npc_from_template` requires `create_npc_from_archetype` (M6.1 NOT_SHIPPED).
- M6.2 → Phase 7 Bestiary: 4 hostile encounters reference creature stat blocks (Bandit, Cult Fanatic, Hollowed Knight, Shadeling, Mawling).
- M6.2 → Phase 9 Economy: merchant-by-tier inventory + personality-by-tier price modifiers feed Phase 9 restock + supply-demand subsystem docs.
- M6.2 → M6.3: settlement-tier ladder gates mentor availability (Hamlet 0 → City 3-6 mentors per spec L578).
- M6.2 → faction system: Ashmark Patrol allied/hostile flip depends on Thornwatch reputation; no encounter-selector consults faction rep today.
- M6.2 → existing location data: `content/locations.json` uses `region_type` ∈ {city, wilderness, dungeon} (`apps/agent/region_types.py:5-9`) — orthogonal axis to settlement_tier; do not collapse.

**Spec/milestone conflicts to record:**
- **Capital tier** has zero in-world examples (spec L556 "None currently exist — the Sundering destroyed the great cities"); milestone L54-55 wants "full role coverage with named authored NPCs." Capital may be post-launch content.
- **Hamlet role-count divergence** — milestone L52 says "1 innkeeper, 1 merchant, 1 healer (partial)"; spec L562-578 says 0-1 innkeeper, 0 merchants, 0 healers (herbalist at best). Milestone overcounts vs spec.
- **`region_type` vs `settlement_tier` orthogonality** — content/locations.json already uses `region_type`; M6.2 introduces `settlement_tier` as a parallel axis. NOT the same thing.
- **`hollow_patrol_greyvale` name collision** with spec's Ashmark Patrol — shipped encounter is Hollow-themed, not Ashmark. M6.2 should add Ashmark Patrol as a new template.

See `audit/phase-6-settlements.md` for the full coverage matrix.

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
- [x] Mentor registry covers all Warrior L4 and L8 technique variants (8+ mentors)
- [x] Rogue mentors cover 5+ technique variants
- [x] Guardian, Skirmisher, Bard, and Spy archetypes each have at least 2 representative mentors <!-- MET 2026-09-01 (story-006): content/mentor_variants.json is now 88 variants / 4 culture-mentors / 44 ability ids. Bard's 4 electives each carry 2 cultural variants, so all four archetypes draw on all 4 culture-mentors. Pinned by test_mentor_variants_content.py + mentor_variants-load.test.ts. -->
- [x] `check_mentor_requirements` correctly evaluates disposition threshold, quest completion, gold, and skill tier
- [x] `check_mentor_requirements` returns specific unmet requirements (not just pass/fail)
- [x] `enroll_mentor_training` validates requirements before enrollment and returns error if unmet
- [x] Training cycles are tracked per player per variant
- [x] Mentor data links correctly to Phase 2 M2.5 ability definitions
- [x] Tests cover requirement combinations (all met, one unmet, multiple unmet)

**Key references:**
- *Game Mechanics NPCs — Mentor Registry*
- *Game Mechanics NPCs — Training Requirements*
- *Game Mechanics Archetypes — Martial Mentor System (M2.5)*

### Audit Status (Sprint-005)

<!-- see audit/phase-6-mentors.md -->

**Status: DELIVERED (culture-mentor model).** Superseded — the Sprint-005 snapshot below is stale. The mentor-variant registry shipped as a culture-mentor model: `content/mentor_variants.json` (88 variants = 4 culture-mentors × 22; all 8 Warrior + all 8 Rogue + Guardian/Skirmisher/Spy + all 4 Bard techniques carry cultural variants) + migrations `035_mentor_variants.sql` / `036_character_mentor_variants.sql` + `apps/agent/mentor_variants.py`, `mentor_requirements.py` (evaluates disposition/quest/gold/skill and returns a specific unmet list), `mentor_variant_progress.py` (per-player-per-variant cycle tracking), and the `learn(variant)` agent tool in `mentor_variant_tools.py` (co-location + requirement gates, ToolError on unmet). Variants link to real base abilities; M9 story-004 made activation explicit, so `activate(variant_id)` uses the variant's cost/effect and `activate(base_id)` keeps the base's. Verified by capstones `tests/acceptance/test_mentor_variants.py` + `test_mentor_gating_e2e.py` and green unit tests (`test_mentor_requirements.py`, `test_mentor_variant_progress.py`, `test_mentor_binding_content.py`). AC3 closed by story-006 (2026-09-01): Bard's 4 electives gained 8 variants; the model stays 4 culture-mentors rather than 2 named mentors per archetype.

The Sprint-005 audit paragraph below is retained for history only.

| Section | BUILT | DESIGNED | NOT_SHIPPED |
| --- | --- | --- | --- |
| M6.3 — Mentor Registry & Training (9) | 0 | 2 | 7 |

**Material gaps:**
- `content/mentor_variants.json` (or migration-seeded `mentor_registry` table) does not exist. Spec defines 22+ named variants across Warrior (16) + Rogue (6) + other archetypes (~5).
- `mentor_registry` DB table — no migration creates it.
- `mentor{}` field on the NPC schema — story-001 audit found it absent from `npc.ts`.
- `variant_id` dimension on `training_activities` — table exists with `data JSONB` but no shipping code stores variant_id.
- 0 of 21+ named spec mentors seeded in `content/npcs.json`. (Probable name-match: Seeker-Agent Emris = `scholar_emris`.)
- `check_mentor_requirements` pure function — 0 hits in apps/agent.
- `enroll_mentor_training` agent tool — not in CITY_TOOLS.
- M2.5 ability symbols — 14 technique_ids referenced by mentor variants have 0 ability binding in apps/agent.

**Cross-doc deps:**
- M6.3 → M6.1: mentor registry binds to NPC schema via `mentor{}` nested field; story-001 finding: NOT_SHIPPED on `npc.ts`.
- M6.3 → Phase 2 M2.5 (Martial Mentor System): compound dep — sprint-002 audit confirms M2.5 is 0/1/6.
- M6.3 → Phase 2 M2.2 (Ability System): chain — M6.3 → M2.5 → M2.2.
- M6.3 → M6.2 Settlements: settlement role-distribution gates mentor availability (npcs.md:578).
- M6.3 → Phase 1 skill tiers + disposition: `check_mentor_requirements` integrates these — both BUILT independently; integration function is the gap.
- M6.3 → quest system: `requirements.quest` references quest ids; no quest-completion gate function exists.

**Spec/milestone conflicts to record:**
- **Warrior mentor count undercount** — milestone says "8+ mentors"; spec ships 16 variants across 8 techniques. Real coverage target is 16.
- **Guardian/Skirmisher/Spy/Bard at 1 per archetype** — milestone L97 says "each have at least 2 representative mentors"; spec ships exactly 1 per archetype.
- **Diplomat archetype NEW** — spec section heading L508 enumerates "Guardian, Skirmisher, Spy, Bard, Diplomat Mentors"; milestone drops Diplomat.
- **`culture` field NEW** — mentor schema spec L390 carries `culture: str` on every variant; milestone L88 omits it.
- **`seeker_emris` vs `scholar_emris` name disambiguation** — spec L505 names "Seeker-Agent Emris"; shipped NPC id is `scholar_emris`. Same character per role match.

See `audit/phase-6-mentors.md` for the full coverage matrix.

---

### Milestone 6.4 — Companion Profiles & Scaling

**Goal:** Implement the 4 named companion archetypes with combat profiles that scale to the player, distinct tactical identities, and a relationship progression system that gates narrative content (not combat power).

**Inputs:** M6.1 (NPC stat blocks), Phase 1 (Core Systems — leveling), Phase 4 (Combat — for companion combat integration).

**Deliverables:**
- 4 companion archetypes with full combat profiles:
  - Kael (martial frontline): absorbs damage, holds the line, protective positioning
  - Lira (arcane investigation): Arcane Bolt, Shield Spell, Elemental Burst, Detect Magic
  - Tam (primal scout): melee/ranged hybrid (Short Sword + Shortbow), Reckless Charge, Nature's Touch
  - Sable (perception/sensing): non-verbal shadow-fox — Bite, Alarm, Distraction
  <!-- CORRECTED 2026-09-01 (decision D-5). The previous four lines had drifted from BOTH the spec and
       the shipped content: they gave Sable the arcane kit that is Lira's, called Lira a healer (she has
       no heal — Kael's Second Wind and Tam's Nature's Touch are the heals), and described Kael and Tam
       as a ranger and a rogue. The canonical table is game_mechanics_npcs.md:676-681, which
       content/companions.json matches exactly; only this milestone doc was wrong. -->
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
- [x] All 4 companions have complete combat profiles with distinct tactical identities
- [x] Each companion has correct count of attacks (2-4), passives (2-3), actives (2-3), reactions (0-1) <!-- MET 2026-09-01 (story-006): Kael 2/2/2/1, Tam 2/2/2/1, Lira 2/2/3/0, Sable 2/3/2/0. Lira gained Radiant Mote, Sable gained Harrying Nip (a non-lethal harry — she stays a scout, not a combatant). Pinned both sides: test_companion_profiles.py::TestParse::test_ability_bucket_cardinality + companion.test.ts. -->
- [x] `scale_companion_stats_to_player_level` produces HP at each companion's `hp_factor` of player HP for levels 1-20 — 0.75 for Kael/Lira/Tam, 0.50 for Sable <!-- AMENDED 2026-09-01 (decision D-4). Was "75% of player HP", which is literally false for Sable (content/companions.json scaling_rules.hp_factor=0.50 vs 0.75 for the other three). The 0.50 is deliberate: Sable is a non-verbal shadow-fox scout (Bite/Alarm/Distraction), and a fox with a warrior's HP is incoherent. RECORDED CONSEQUENCE: game_mechanics_npcs.md:636 ties the 75% figure to encounter math — "the encounter scaling in game_mechanics_bestiary.md assumes 1 player + 1 companion = 1.75x a single character". A Sable party is ~1.6x, not 1.75x. Phase 7 M7.4 build_encounter MUST read actual companion hp_factor rather than assuming 0.75 (companion_scaling.py:43); filed as an explicit input to Milestone 34. -->
- [x] All 5 relationship tiers defined with narrative content gates
- [x] Relationship tier does NOT affect combat stats or ability availability
- [x] Hostile encounter templates reference correct companion combat behaviors
- [x] Companion stat blocks pass same validation as NPC stat blocks (shared schema base)
- [x] Tests cover scaling at level boundaries (1, 5, 10, 15, 20) and all relationship tier transitions
- [x] `content/companions.json` contains all 4 companions with full data

**Key references:**
- *Game Mechanics NPCs — Companion Archetypes*
- *Game Mechanics NPCs — Companion Scaling*
- *Game Mechanics NPCs — Relationship Progression*
- *Game Mechanics NPCs — Hostile Encounter Templates*

### Audit Status (Sprint-005)

<!-- see audit/phase-6-companions.md -->

**Status: DELIVERED (capstone `test_m6_4_companion_chain_capstone.py` passes; 1 AC deferred).** Superseded — the Sprint-005 snapshot below is stale. Shipped: `content/companions.json` (all 4 companions — Kael/Lira/Tam/Sable — with typed `attacks`/`passives`/`actives`/`reactions` buckets, `scaling_rules`, `relationship_unlocks`) + migrations `042_companions.sql` / `043_companion_affinity.sql` + `apps/agent/companion_profiles.py`, `companion_scaling.py` / `hp_scaling.py` (`scale_companion_stats_to_player_level`, HP at hp_factor of player max — 0.75, Sable 0.50), `companion_relationship.py` (5 named tiers New/Warming/Trusted/Bonded/Legendary gating narrative unlocks only). Combat stat block proven relationship-independent through the real `_start_combat_impl` path. The 4 hostile-encounter templates ship in `content/encounter_templates.json`. Deferred (left unchecked): AC2 — Lira and Sable each carry 1 attack, below the stated 2–4 range (intentional support/glass-cannon profiles), so the strict count criterion is not met.

The Sprint-005 audit paragraph below is retained for history only.

| Section | BUILT | DESIGNED | NOT_SHIPPED |
| --- | --- | --- | --- |
| M6.4 — Companion Profiles & Scaling (9) | 1 | 3 | 5 |

**Material gaps:**
- `content/companions.json` does not exist. Only Kael in `content/npcs.json` with partial fields.
- `companions` + `companion_relationships` DB tables — no migration creates them. `CompanionState` is in-memory session state only.
- Typed ability buckets (attacks/passives/actives/reactions) — Kael's `action_pool` is a flat list of 2 untyped entries.
- 6 of 7 Kael spec abilities unshipped (Shield Bash, Protective Instinct, Veteran's Resilience, Hold the Line, Second Wind, Intercept).
- 0 abilities for Lira/Tam/Sable; narration shims only.
- HP scaling function (`scale_companion_stats_to_player_level`) and relationship query function (`query_companion_relationship`) — 0 grep hits.
- Named relationship tiers (New/Warming/Trusted/Bonded/Legendary) — int tracker ships, semantic tier registry does not.

**Cross-doc deps:**
- M6.4 → M6.1: companion stat blocks reuse NPC schema; M6.4 ability-bucket fields not on the schema (story-001 finding).
- M6.4 → M6.2: 4 hostile encounter templates inherited (story-002 audit owns canonical); story-002 punch list recommends M6.2 as primary owner.
- M6.4 → Phase 4 Combat: companion-in-combat integrated via `CombatParticipant` + `combat_init.py`; companion ability execution (Hold the Line, Second Wind, Intercept) is the gap.
- M6.4 → Phase 7 Bestiary: companion stat blocks inherit from CreatureStatBlock (unshipped).
- M6.4 → Phase 3 Magic: Sable mage profile references Focus pool + spell catalog.
- M6.4 → faction system + quest system: Companion Assignment Logic + Companion Progression Milestones consume both.

**Spec/milestone conflicts to record:**
- **CompanionState infrastructure NEW** vs M6.4 deliverable list — idle speech, emotional state, session memory, 4 narration shims ship beyond what milestone enumerates. Promote to M6.4 or split into M6.5 (Companion Presence Layer).
- **Errand-bonus relationship_tier coupling** at `async_rules.py:143-147` — NEW out-of-combat mechanic not in milestone (doesn't violate bullet 5, but is undocumented coupling).
- **Kael action_pool flat-list divergence** — shipped `combat_stats.action_pool` is a flat 2-entry list; spec wants typed buckets. NPC schema split decision needed.
- **Defensive Stance vs Shield Bash** — shipped 2nd attack diverges from spec's 2nd attack name and shape.
- **Sable non-verbal TTS handling** — voice-registry decision needed (suppress vs growl-only).

See `audit/phase-6-companions.md` for the full coverage matrix.
