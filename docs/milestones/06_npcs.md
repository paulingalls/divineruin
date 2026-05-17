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

### Audit Status (Sprint-005)

<!-- see audit/phase-6-schema-archetypes.md -->

**Status: DESIGNED.** Narrative/social NPC layer is shipped — 14-entry `content/npcs.json` rides `packages/shared/src/entities/npc.ts:17-39`, `npc_dispositions` table persists per-player disposition, and `apps/agent/tool_support.py:86-105` `filter_knowledge` enforces disposition-gated knowledge with test coverage. The mechanical archetype layer is unshipped: `services[]`, `price_modifier`, `mentor{}`, and `role_archetype` template-link fields are absent from the schema and content; no `role_archetypes` template store exists (no JSON file, no DB table, no Python module); no `create_npc_from_archetype` function. 14 shipped NPCs are all Tier-1 authored; 0 of 12 archetype templates seeded.

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
- **Quest Giver** archetype (gm_npcs L190-206) is NEW vs milestone's 12 — spec explicitly notes "Not a standalone role." Treat as `quest_giver?: bool` flag or function overlay. Tracked in `audit/README.md` Sprint-spec-cleanup.
- **Shipwright** archetype (gm_npcs L370-375) is NEW vs milestone's 12 — milestone undercounts by 1. Tracked in `audit/README.md` Sprint-spec-cleanup.

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

### Audit Status (Sprint-005)

<!-- see audit/phase-6-settlements.md -->

**Status: NOT_STARTED.** M6.2 is entirely unshipped. No settlement_tier ladder (Hamlet/Village/Town/City/Capital) in code or content — `packages/shared/src/entities/location.ts:28` `tier: 1 \| 2` is the entity authored/template flag, not the settlement size enum. No personality-trait enum (the 8 spec traits are not constants, not enum members, not seed data). The three generation surfaces (`generate_settlement_npcs`, `instantiate_npc_from_template`, `get_settlement_npc_population`) return 0 grep hits. No `settlement_templates` migration. The 4 spec hostile-encounter templates (Bandit Ambush, Ashmark Patrol, Cult Cell, Hollow-Corrupted Settlement) are NOT in `content/encounter_templates.json` (6 shipped entries are all Hollow-themed); the `encounter_templates` storage table itself ships in migration 001, content does not.

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

### Audit Status (Sprint-005)

<!-- see audit/phase-6-mentors.md -->

**Status: NOT_STARTED.** Mentor registry is almost entirely unshipped, but the training-cycle infrastructure underneath it is real. What ships: generic 5-state async-training state machine (migration 016 `training_activities`), 8 activity types including `technique_mentor` (migration 017 + `content/training_activity_types.json`), 4 training programs with `mentor_id` field referencing 2 NPC narration shims (`guildmaster_torin`, `scholar_emris`). What does NOT ship: mentor-variant registry table, 0 of 21+ named spec mentors seeded (Warrior 16 variants, Rogue 6 variants, other archetypes 5), `check_mentor_requirements` / `enroll_mentor_training` surfaces, per-variant cycle persistence, and the M2.5 ability symbols (Cleaving Blow, Precision Strike, etc.) the registry would link to. Compound dependency: per sprint-002 audit, M2.5 itself is 0/1/6 — bullet 8 (M2.5 link) is structurally NOT_SHIPPED because M2.5's ability surface is itself NOT_SHIPPED.

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

### Audit Status (Sprint-005)

<!-- see audit/phase-6-companions.md -->

**Status: PARTIAL.** Richest partial-implementation surface in sprint-005. **One acceptance bullet genuinely BUILT** (bullet 5 — relationship tier does NOT affect combat, negative-condition honored by absence of coupling code: `combat_stats` is read from content independent of `CompanionState.relationship_tier`). **Three DESIGNED**: bullet 1 (Kael partial in `content/npcs.json:147-223`, Lira/Tam/Sable narration shims only); bullet 4 (5 relationship tiers — int tracker `apps/agent/session_data.py:22` + display `warm_prompts.py:180` + errand bonus `async_rules.py:143-147`; named tiers + narrative gates absent); bullet 7 (companion validates-as-NPC, but only because M6.4 ability-bucket fields aren't there to validate). **Five NOT_SHIPPED**: typed ability buckets, HP scaling function, hostile encounter integration (cross-ref M6.2), scaling+tier tests, `content/companions.json`.

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
