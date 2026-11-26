# Phase 7: Bestiary & Encounters

> Source doc: `docs/game_mechanics/game_mechanics_bestiary.md`

Defines the full creature catalog, from stat block schema through regional creatures, Hollow special mechanics, and the encounter builder. Provides the DM agent with a complete library of adversaries and the tools to assemble balanced encounters.

## Catalog and Generated Entry Status

<!-- see audit/phase-7-bestiary.md and audit/phase-encounter-roles.md -->

**Status: PARTIAL.** The Python and TypeScript validators, queryable `creatures` table, all 9 spec-authored Hollow creatures, all 19 spec-authored natural creatures and eight encounter creature catalog rows ship. `query_info(kind="creature")` exposes catalog summaries by id or session region and party tier, plus party-fit unbound `encounter_templates` ids. `enter_mode(mode="combat")` starts authored templates or difficulty-driven generated encounters through the same locked initializer and persisted snapshots. Harvesting, immediate and async purification, and M7.4 composition ship. All 43 recorded criteria are checked. Native Choir audio certification remains open.

| Section | Confirmed | Partial | NOT_SHIPPED |
| --- | --- | --- | --- |
| M7.1 — Creature Stat Block Schema | 9 | 0 | 0 |
| M7.2 — Regional Creature Catalog | 11 | 0 | 0 |
| M7.3 — Hollow Creatures (Special Mechanics) | 12 | 0 | 0 |
| M7.4 — Loot, Harvesting & Encounter Builder | 11 | 0 | 0 |

**Catalog cutover and inventory refresh:** All 16 ordinary authored encounters (17 total templates; 17 ordinary species and 18 including the Choir) store catalog references, explicit roles and recommended party levels; combat expands these references into persisted snapshots. The bestiary Combat Effect Inventory records the supported paths and their remaining limits. Social `command` and `accusation` effects carry narrative-only focus/narration, without automatic healing or spell buff dice. Choir Deafened restrictions, Charmed movement, silence and core phases execute through structured combat paths. The Still's anchors and the Architect's terrain and legendary mechanics execute through combat. The live Combat Effect Inventory names each executable, mixed and narrative-only effect. Fixed-seed CLI fights reach victory for Shadeling, young, adult-minion and standard-adult Mawling, Hollowmoth and Weaver. Blinding Swarm, Rearrange and Spatial Fold remain DM-narrated. Passive and prose limits remain in the exact deferred-effects map in `test_creature_combat.py`.

Material changes publish immediate owner-scoped agent snapshots after commit. HTTP crafting consumption and keep grants return a full committed HTTP snapshot to the initiator. Other devices use authenticated GET /api/inventory on HUD open/resume and every five seconds while foreground with any HUD panel open, independently of voice connectivity. Background, closed HUD and unmount stop polling. Snapshot generation rejects an older pending GET or mutation snapshot after an immediate update; auth transitions invalidate pending responses. A refresh error preserves inventory and displays retry status; the next scheduled poll retries. The five-second cross-device delay is the accepted tradeoff; no room registry or server packet impersonates the agent.

**Remaining mechanics and integration:**
- **M7.1 schema extensions needed for encounter_roles:** the spec's universal stat block still needs optional `role` (Minion/Standard/Elite/Boss/Named) and Boss-only `legendary_actions[]` for the Phase-7 catalog. Optional `signature_ability` now has a typed catalog home; M4.7 already derives roles from authored templates.
- **M7.2 region-count gap (capstone decision `m7-2-creature-count-gap`):** the earlier milestone count claimed "38+ natural creatures" and named Ashmark Soldier and Cult Acolyte. The spec authors **19 natural creatures** (4 Greyvale + 2 Thornveld + 2 Drathian Steppe + 3 Keldaran + 2 Sunward + 2 Underground + 4 Multi-Region). The milestone count now matches the spec. Ashmark Soldier and Ashmark Sergeant ship in `content/encounter_templates.json` (`ashmark_patrol`); Cultist, Cult Fanatic, and Cult Leader ship there in `cult_cell`. Those five and three Hollow encounter enemies now have spec blocks and catalog rows, and their encounter entries now reference those catalog rows. Cult Acolyte still has no block because no encounter uses it. All 19 natural rows ship in the Phase-7 catalog; generated combat now uses these rows through the shared entry path.
- **M7.3 combat evidence:** cast-time Hollow auras and death Resonance execute, and the Choir adds turn-start concentration saves. Mawling standard two-strike and elite/boss three-strike multiattack, Dissolution Maw item wear, and source-owned grapple turn-start damage also execute. Fallen damage adds one death-save failure through the shared damage path; a landed melee attack within 5 ft adds two, including queued strikes after an ally falls. Players cap at three failures; companions stabilize at phase wrap. `test_fallen_melee_failures.py` covers persisted distance boundaries, the Hollowed echo, other damage modes and companion stabilization. Troop and Tier 3 prose limits are listed in the Combat Effect Inventory.
- **M7.4 pure builder API:** `build_encounter(catalog, tier, party, environment, difficulty, rng)` selects catalog references with profile-weighted budget and expected-round bounds. Players supply levels; companions supply owner IDs and profile HP factors; environment is already resolved. `enter_mode` resolves location region/terrain and player levels, uses active companion profile factors, and persists the expanded generated combat. Omitted tier uses the floor-mean player level; location tier is unrelated. Expected-round windows are HP/DPR bounds, not measured combat-duration certification.

**encounter_roles cross-ref:** Phase 04 is primary owner per `04_combat.md` Sprint-003 status. Phase 07 cross-refs Role Definitions (creature roles in bestiary) and Worked Example stat blocks. The encounter_templates.json `role` strings on NPCs (`content/npcs.json`) are narrative-only ("guild hall master") and do NOT carry the M4.7 EncounterRole enum.

See `audit/phase-7-bestiary.md` for the full 41-item coverage matrix.

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
- Loot schema: `loot_table_id` referencing `content/loot_tables.json`; its drops carry chance and quantity, and the table carries `hollow_residue`
- XP reward per creature
- Tier system constants: Tier 1 (player L1-4), Tier 2 (L5-8), Tier 3 (L9-14), Tier 4 (L15-20)
- DB migration: `creatures` table with full stat block schema and JSONB fields for nested data
- Validation: `validate_creature_stat_block(creature)` ensuring all required fields and internal consistency
- Optional combat fields: attacks may carry `properties[]`, condition/save fields, `escape_dc`, structured `recharge`, boolean `advantage`, and positive integer `duration`. Typed actives distinguish attacks, direct `healing` and `prepare_attack` from social `command`/`accusation`; untyped actives remain narrative. Present catalog signatures require `name`, `description`, and nonblank sound-first `narration_cue`. Both authored signatures now preserve matching cues and mechanics through seed/query. See the bestiary Combat Effect Inventory for every selected species' supported, scheduled, duplicate and deferred effect. Combat executes the supported attack, healing, preparation and limited-use paths; catalog expansion exposes their IDs and authored cues to the DM. All 16 templates now use catalog references. Rows without optional extensions remain valid.

**Acceptance criteria:**
- [x] Schema supports all 6 creature categories with shared base fields <!-- verified apps/agent/tests/test_creature_schema.py::test_shared_creature_corpus; packages/shared/src/entities/creature.test.ts::shared_creature_corpus -->
- [x] Hollow-specific nested fields are optional and only validated when category is "hollow" <!-- verified apps/agent/tests/test_creature_schema.py::test_shared_creature_corpus -->
- [x] All attack entries include the canonical template’s name, type, reach, to_hit, damage, damage_type, special, and audio <!-- verified apps/agent/tests/test_creature_schema.py::test_every_spec_field_is_required; supersedes the older attribute/damage_dice/range wording -->
- [x] Tier system correctly maps tiers 1-4 to player level ranges <!-- verified apps/agent/tests/test_creature_tiers.py::test_every_player_level_has_exactly_one_tier; the TypeScript mirror is pinned in packages/shared/src/entities/encounter.test.ts -->
- [x] Narration fields provide audio-first cues (sound/smell before sight) <!-- verified apps/agent/tests/test_creature_catalog_content.py::test_narration_opens_with_sound_or_smell; apps/agent/tests/test_creature_schema.py::test_hollow_exemplar_fixtures_match_catalog -->
- [x] Loot schema supports both guaranteed and probabilistic drops <!-- verified apps/agent/tests/combat/test_encounter_loot.py::test_boss_loot_is_guaranteed_and_boosts_quantity; apps/agent/tests/combat/test_encounter_loot.py::test_standard_loot_omits_entries_whose_chance_fails; `loot_table_id` supersedes nested guaranteed[]/chance[] loot -->
- [x] `validate_creature_stat_block` rejects invalid entries with specific error messages <!-- verified apps/agent/tests/test_creature_schema.py::test_shared_creature_corpus -->
- [x] DB migration runs cleanly with proper indexes on category, tier, and name <!-- verified apps/agent/tests/acceptance/test_creature_catalog.py::test_catalog_columns_and_indexes -->
- [x] Tests cover validation for all 6 categories including Hollow edge cases <!-- verified apps/agent/tests/test_creature_schema.py::test_shared_creature_corpus -->

**Key references:**
- *Game Mechanics Bestiary — Creature Stat Block Template*
- *Game Mechanics Bestiary — Tier System*
- *Game Mechanics Bestiary — Loot Schema*

---

### Milestone 7.2 — Regional Creature Catalog

**Goal:** Author all 19 natural (non-Hollow) creatures, including the underground pair and four multi-region threats, with complete stat blocks, distinct behavior, and audio-first cues across the six spec regions.

**Inputs:** M7.1 (creature stat block schema).

**Deliverables:**
- 19 natural creature entries across the specified regions, fully authored:
  - Greyvale: Grey Wolf, Wild Boar, Giant Spider, Bandit (Tier 1)
  - Thornveld: Thornveld Stalker, Corrupted Treant (Tier 1-2)
  - Drathian Steppe: Steppe Razorwing, Steppe Bison (Tier 1)
  - Keldaran Mountains: Rock Viper, Cave Wyrm, War Golem (Tier 1-3)
  - Sunward Coast & Wetlands: Saltmarsh Lurker, Tidecaller Eel (Tier 1-2)
  - Underground: Umbral Crawler, Deepstone Guardian (Tier 2)
  - Multi-region: Dire Bear, Troll, Bandit Captain, Thunderbird (Tier 2-3)
- Each creature: full stat block, 1-3 attacks, behavior pattern (aggressive/defensive/pack/ambush), retreat condition, narration cues, audio hints
- Bandit and Bandit Captain use equipment attacks; Troll uses its specified natural attacks
- Content: all creatures authored in `content/creatures.json` organized by region
- Internal function: `query_creatures_by_region(region_id, tier=None)` returning matching creatures
- Internal function: `query_creature_by_id(creature_id)` returning full stat block

**Acceptance criteria:**
- [x] All 19 natural creatures have complete stat blocks passing M7.1 validation <!-- verified apps/agent/tests/test_creature_catalog_content.py::test_real_validators_and_seed_submission; apps/agent/tests/test_creature_distribution.py::test_natural_creature_distribution -->
- [x] Every spec region has at least 3 natural creatures, with distribution counts pinned by region <!-- verified apps/agent/tests/test_creature_distribution.py::test_natural_creature_distribution -->
- [x] Greyvale home-region creatures are Tier 1 only (starter region) <!-- verified apps/agent/tests/test_creature_distribution.py::test_natural_creature_distribution -->
- [x] Keldaran Mountains include Tier 3 creatures (late-game region) <!-- verified apps/agent/tests/test_creature_catalog_content.py::test_spec_stats_regions_and_behavior -->
- [x] Each natural creature has a distinct behavior pattern (tactics) and retreat threshold (morale) <!-- verified apps/agent/tests/test_creature_distribution.py::test_natural_creature_distribution -->
- [x] Natural creature narration cues follow the audio-first convention <!-- verified apps/agent/tests/test_creature_catalog_content.py::test_narration_opens_with_sound_or_smell -->
- [x] Bandit and Bandit Captain have their specified equipment attacks; Troll has its specified Claw and Bite <!-- verified apps/agent/tests/test_creature_catalog_content.py::test_spec_stats_regions_and_behavior -->
- [x] Internal function `query_creatures_by_region` filters correctly by region and tier <!-- verified apps/agent/tests/acceptance/test_creature_catalog.py::test_public_creature_queries -->
- [x] Internal function `query_creature_by_id` raises on nonexistent IDs <!-- verified apps/agent/tests/acceptance/test_creature_catalog.py::test_public_creature_queries -->
- [x] `content/creatures.json` passes schema validation for all entries <!-- verified packages/shared/src/entities/creature.test.ts::real_catalog_and_injected_invalid_entry; apps/agent/tests/acceptance/test_creature_catalog.py::test_catalog_columns_and_indexes -->
- [x] Tests verify exact natural creature distribution, Greyvale home tiers, and Keldaran Tier 3 presence <!-- verified apps/agent/tests/test_creature_distribution.py::test_natural_creature_distribution -->

All 19 spec-authored natural catalog rows ship, including the underground pair and four multi-region threats. Their linked loot tables retain every representable spec quantity and harvest requirement. Greyvale's four home-region rows are Tier 1; War Golem gives Keldaran a Tier 3 home row. Bandit and Bandit Captain use their spec equipment attacks; the Troll uses Claw and Bite. The Captain's catalog table uses chain shirt, quality longsword, and map or intel, and catalog-backed encounter captains use that table. Coin pouches and variable stolen goods are omitted because the item-drop schema cannot represent them.

An attack's rider poison damage stays in `special`, while `damage` records its base hit (Giant Spider and Rock Viper). The `speed` field holds ground speed. Hollowmoth, Steppe Razorwing, and Thunderbird use their `fly_speed` for melee approaches and close on the ground where a lowered ceiling blocks flight. Climb, burrow, and swim speeds remain in ability descriptions. Tier 3 `cave_wyrm_scales` can drop from the Tier 2 Cave Wyrm because material tier and creature tier have separate meanings. Guardian Pulse and Lightning Breath use `type: area` with schema-required unused `to_hit: 0`; their saves and areas remain in `special`. Dire Bear's Maul also carries `to_hit: 0`; its auto-hit against grappled targets lives in `special`.

**DM surface:** `query_info(kind="combat")` surfaces Choir search and core facts (`apps/agent/tests/acceptance/test_choir_encounter.py`). `query_info(kind="creature")` exposes creature summaries and a party-fit `encounter_templates` list for `enter_mode`.

**Key references:**
- *Game Mechanics Bestiary — Regional Creatures*
- *Game Mechanics Bestiary — Creature Behavior Patterns*
- *Game Mechanics Bestiary — Humanoid Enemies*

---

### Milestone 7.3 — Hollow Creatures (Special Mechanics)

**Goal:** Implement the 9 Hollow creatures with unique combat mechanics that break standard patterns, including corruption auras, resonance interactions, and the 3 Tier 4 boss creatures with custom behavior systems.

**Inputs:** M7.1 (creature stat block schema with Hollow extensions), Phase 3 (Magic — Resonance system for resonance_on_death interaction).

The catalog includes all nine spec Hollow creatures, including the three Tier 4 Named. The Choir has a Search/Exposed/Destroyed core, DC18 sound search, turn-start DC15 concentration aura, one real-cast Harmonic Shield redirect, three-round Silence Void, structured Deafened, and death Resonance. A level-16 party can take the northeast exit from the Ashmark Front to The Lost Voices, where the scene offers the Choir fight for a recommended party of 2+ (`test_encounter_templates_surface_entry.py::test_shipped_boss_discovery`). Fixed seeds 0 and 1 reach core victory from The Lost Voices with every kit action, a Harmonic Shield redirect, a hold and reload, and one-time settlement (`test_choir_fight.py`). Entering existing silence and casting Silence Void each suppress the Choir's next turn. Native audio certification remains pending. The Still is fought through six hidden anchors (DC 18 Perception or Arcana reveals one) in the deep-Ashmark `ashmark_still`; it stays passive until an anchor is attacked, answers with Rejection from that anchor, and falls when the last anchor breaks. Its zone charm (Paradise Trap, Serenity's Touch, Final Stillness) holds the party in place, re-saves each in-zone hour (paused in combat) and drains daily toward character death (`test_still_anchors.py`, `test_still_rejection.py`, `test_still_paradise_trap.py`, `test_still_absorption.py`, `test_still_rally_exclusion.py`). Fictional silence and Deafened restrict legal actions but keep the microphone command path active (`test_voice_condition_commands.py`). The Hollowed Knight encounter uses its catalog loot table. Mawling's Lunge carries structured recharge, advantage, and grapple fields into combat.

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
- [x] All 9 Hollow creatures have complete stat blocks with hollow nested fields populated <!-- verified apps/agent/tests/test_hollow_catalog.py::test_all_spec_hollow_ids_have_complete_blocks -->
- [x] Corruption aura applies correctly based on distance and target saves <!-- verified apps/agent/tests/test_hollow_resonance.py::test_boundary_and_contact; apps/agent/tests/combat/test_hollow_resonance_lifecycle.py::test_actual_catalog_cast_aura_boundary; apps/agent/tests/combat/test_choir_encounter.py::test_choir_aura_turn_start_once_across_hold_resume, ::test_choir_aura_movement_uses_turn_start_position, ::test_choir_aura_eligibility_and_success; apps/agent/tests/acceptance/test_choir_encounter.py::test_choir_aura_concentration_member_isolation_reload; apps/agent/tests/combat/test_veilrender.py::test_field_turn_start_targets, ::test_field_once_across_hold_reload -->
- [x] `resolve_resonance_on_death` feeds correct Resonance deltas to nearby casters <!-- verified apps/agent/tests/combat/test_hollow_resonance_lifecycle.py::test_death_recipients_and_cross_source_caster apps/agent/tests/acceptance/test_hollow_resonance_commit.py::test_commit_routes_qualitative_states_and_resume_is_once -->
- [x] Each Hollow creature has a distinct veil_effect and vulnerability <!-- verified apps/agent/tests/test_hollow_catalog.py::test_all_hollow_veil_effects_and_vulnerabilities_are_pairwise_distinct -->
- [x] The Choir has custom multi-phase audio-zone combat behavior (not standard attack loop) <!-- verified apps/agent/tests/acceptance/test_choir_fight.py -->
- [x] The Still has passive-until-attacked behavior with anchor-based Rejection (spec `game_mechanics_bestiary.md` Rejection; the spec has no damage reflection — human 2026-11-17) <!-- verified apps/agent/tests/acceptance/test_still_anchors.py::test_still_entry_search_and_weapon_damage, ::test_still_flee_reload_and_settle_once; apps/agent/tests/acceptance/test_still_rejection.py::test_anchor_miss_wakes_still_only_when_resolved, ::test_rejection_only_recharges_with_a_pending_anchor_attack; apps/agent/tests/acceptance/test_still_paradise_trap.py; apps/agent/tests/acceptance/test_still_absorption.py -->
- [x] The Architect has terrain manipulation abilities that alter combat grid state <!-- verified apps/agent/tests/acceptance/test_architect_fight.py, test_architect_terrain.py, test_architect_reshape.py, test_architect_reshape_reload.py, test_architect_reaction.py, test_architect_entomb.py, test_architect_entomb_release.py, test_architect_cathedral.py, test_architect_constructs.py, test_architect_legendary.py, test_architect_reentry.py, test_architect_balance.py -->

  Architect: walls are persisted segments that block movement, reach and every line (full cover, no pathing). Reshape raises and moves walls, opens floor pits and lowers ceilings. Reactive Architecture raises one reaction wall a round, which crumbles at the round's end. Entomb, Cathedral, Summon Constructs, legendary actions and Legendary Resistance resolve mechanically; only Alien Intelligence is narrated. The warrior took Precision Strike at level 4 and Iron Stance at level 8. The rogue took Dirty Trick at level 4 and Blade Flurry at level 8. The level-20 party of four with earned gear, electives and patrons won 12 of 20 fixed seeds in a median of 18 rounds at 205 HP (spec 300). This was the highest passing 5 HP step of a full 175–300 HP scan. The measured dice were Construct Slam `2d10+4` plus `1d6` force, Geometry Strike `1d8+6`, Cathedral `2d10`, and Entomb compression `2d8`. The bestiary records every deviation beside spec. The bestiary's Weaver effects (Rearrange, Spatial Fold) are not delivered by this box and stay DM-narrated deferred effects.
- [x] Tier 1-2 Hollow creatures function as standard combat encounters (no custom behavior needed) <!-- verified apps/agent/tests/acceptance/test_hollow_troops_fight.py; apps/agent/tests/combat/test_hollow_troops_balance.py; apps/agent/tests/acceptance/test_encounter_templates_surface_entry.py -->
- [x] Tier 3 Hollowed Knight and Veilrender have boss-tier HP and multi-phase mechanics <!-- verified apps/agent/tests/acceptance/test_hollowed_knight_fight.py, apps/agent/tests/acceptance/test_veilrender_fight.py, apps/agent/tests/combat/test_veilrender_absorb.py, apps/agent/tests/acceptance/test_veilrender_absorb_commit.py -->

  Knight: `hollow_knight_boss` has boss HP, paired Blades, typed necrotic riders, magical-weapon resilience and escalating Unholy Fortitude across hold/reload (`test_hollowed_knight_fight.py`, `combat/test_hollowed_knight.py`). Hard at L14 with two mawlings, recommended party 2+. Veilrender uses its standard bestiary block (120 HP, AC 14), Corruption Field, regeneration, durable radiant/ward suppression, Reality Crush and one Corruption Pulse. Both bosses are discoverable and startable from the shipped Ashmark Front (`test_encounter_templates_surface_entry.py::test_shipped_boss_discovery`). Veilrender is hard at L14, recommended party 2+; the L9–14 solo tuning bar did not pass. Fixed seeds 0 and 1 reach terminal outcomes through real tools with holds, reloads, suppression and resumption (`test_veilrender_fight.py`). Absorb Magic is exercised through real casts: non-radiant recipients heal once per cast, radiant spells bypass and suppress regeneration, and absorption rolls back with casting costs. Siege Monster, Massive, the push, structural damage, environmental decay, Remnant Tactics, Fragment Voice and the corrupted-terrain patch remain narrated. Corruption Wave resolves its participant-aimed cone, excluding its source.
- [x] Tests cover corruption aura at various distances, resonance_on_death, and all 3 Tier 4 custom behaviors <!-- verified apps/agent/tests/test_hollow_resonance.py; apps/agent/tests/combat/test_hollow_resonance_lifecycle.py; apps/agent/tests/acceptance/test_hollow_resonance_commit.py; apps/agent/tests/acceptance/test_still_anchors.py; apps/agent/tests/acceptance/test_still_rejection.py; apps/agent/tests/acceptance/test_architect_fight.py; apps/agent/tests/acceptance/test_choir_fight.py -->
- [x] Stage 2 Hollowed delivers hallucinations. Stage 3 drains 1 Wisdom per long rest down to 1. Greater Restoration clears Hollowed at any stage and restores its recorded Wisdom loss, up to 20. <!-- verified apps/agent/tests/acceptance/test_hollowed_progression.py, apps/agent/tests/acceptance/test_hollowed_wis_drain.py, apps/agent/tests/acceptance/test_greater_restoration.py -->
- [x] Equipped catalog magical weapons and weapons made magical by Artificer Infuse Item bypass the Knight's physical resistance (`test_magical_weapons.py`, `test_infuse_item.py`).

**Key references:**
- *Game Mechanics Bestiary — Hollow Creatures*
- *Game Mechanics Bestiary — Corruption Aura*
- *Game Mechanics Bestiary — Resonance on Death*
- *Game Mechanics Bestiary — Tier 4 Boss Behaviors*

---

### Milestone 7.4 — Loot Tables, Harvesting & Encounter Builder

**Goal:** Implement the loot generation system with skill-gated harvesting and the encounter builder that assembles balanced combat encounters from the creature catalog. Loot generation enforces every authored skill requirement against the best tier per skill among player combat participants; different participants may supply different skills. Hollow residue remains a data flag.

**Inputs:** M7.1-M7.3 (creature catalog), Phase 1 (Core — skill tiers for harvesting gates), Phase 5 (Crafting — for material-to-recipe pipeline integration).

The Warden's spec block (Encounter Creature Stat Blocks) names `loot_hollow_warden` and authors no drops of its own. The table's residue flag and Crafting:Expert harvest gate follow the rend table's residue precedent; they do not imply a spec drop for the Warden.

**Deliverables:**
- Loot generation: `generate_loot(loot_table, role, party_tiers, rng)` returning guaranteed drops plus probabilistic rolls
- Skill-gated harvesting follows the bestiary's Harvesting Skill Requirements table (`game_mechanics_bestiary.md:1173-1183`); each gated drop names one material `kind`, and each kind maps to exactly one skill/tier pair:
  - None — obvious items (coins, fangs, dropped weapons, loose materials)
  - Survival:Trained — pelts, meat, basic organs, common plant materials
  - Survival:Expert — venom sacs, intact glands, rare organs, volatile materials; also rare gems (`rare_gem`, project decision, not in the spec table)
  - Crafting:Trained — crafting-grade construct materials, salvageable components
  - Crafting:Expert — Hollow residue, delicate/volatile materials
  - Arcana:Trained — magical components from magical creatures
  - Arcana:Expert — Named creature fragments, high-tier arcane components, Veil shards
- Hollow loot tainting: all Hollow creature drops flagged as tainted by default
- Purification paths: Clerics use Dispel Corruption to purify a whole tainted inventory stack immediately for the selected party player owner, spending normal Focus. `item:<owner_player_id>:<item_id>` selects the object; `corruption_saturated_stone` is unpurifiable. Purified `salvageable_weapon` yields usable standard martial equipment (`battleaxe_common`). Artificers escrow a chosen quantity of tainted units for three independently sampled Crafting skill-practice cycles; the worker credits the clean output exactly once before collection acknowledges it.
- Pure encounter builder: `build_encounter(catalog, tier, party, environment, difficulty, rng)` returning role-tagged catalog references
- Solo player HP math: profile factors weight budget and DPR (Kael/Lira/Tam 0.75; Sable 0.50), against the 1.75 baseline
- Environment modifiers: terrain type affects creature selection and combat difficulty
- Encounters tuned for their difficulty's expected HP/DPR round window (standard 3-5, tough 4-6, boss 5-7)
- Agent entry: `enter_mode(mode="combat", difficulty="standard"|"tough"|"boss", tier=None)` generates a location-filtered encounter; `encounter_id` selects a mutually exclusive template.
- Agent catalog reads: `query_info(kind="creature", target_id=None)` returns a creature summary by id, or returns `creatures` for the session region at the party tier and `encounter_templates` eligible by floor-mean party level and every species’ region/terrain, excluding quest/scene bindings. Harvesting runs automatically with victory loot generation at combat end.

**Acceptance criteria:**
- [x] `generate_loot` returns guaranteed drops always and probabilistic drops at correct rates
- [x] Harvesting requires the correct skill tier per the spec's Harvesting Skill Requirements table: every gated drop's kind maps to one spec pair
- [x] Party without a required skill tier gets no harvesting drop (gated out before rolling)
- [x] All Hollow creature loot is flagged tainted; non-Hollow loot is not
- [x] Purification via Dispel Corruption clears taint flag; async purification tracks activity timer <!-- verified apps/agent/tests/acceptance/test_dispel_corruption.py; apps/agent/tests/acceptance/test_dispel_corruption_atomicity.py; apps/agent/tests/acceptance/test_async_purification.py; apps/agent/tests/acceptance/test_async_purification_atomicity.py -->
- [x] `build_encounter` selects creatures matching requested tier and scales to combatant count <!-- verified apps/agent/tests/acceptance/test_generated_combat.py::test_generated_entry_resume; apps/agent/tests/test_encounter_builder.py -->
- [x] Solo encounters use the active companion's profile factor (Kael/Lira/Tam 0.75; Sable 0.50) for budget and expected damage <!-- verified apps/agent/tests/acceptance/test_generated_combat.py::test_generated_entry_resume; apps/agent/tests/test_encounter_builder.py -->
- [x] Environment modifiers adjust creature selection (e.g., no aquatic creatures in mountains) <!-- verified apps/agent/tests/acceptance/test_generated_combat.py; apps/agent/tests/acceptance/test_creature_terrains.py; apps/agent/tests/test_encounter_builder.py -->
- [x] Generated encounters resolve in their difficulty's round window given expected player damage output (standard 3-5, tough 4-6, boss 5-7) <!-- verified apps/agent/tests/acceptance/test_generated_combat.py::test_generated_entry_resume; apps/agent/tests/test_encounter_builder.py -->
- [x] Every loot item is named by a Phase 5 recipe material or marked `crafting_use: "trade"` on its unique catalog owner
- [x] Tests cover loot generation for all creature categories, harvesting skill gates, encounter scaling, and environment filtering <!-- verified apps/agent/tests/acceptance/test_loot_catalog.py::test_every_category_victory_loot; apps/agent/tests/acceptance/test_loot_skill_gates.py; apps/agent/tests/acceptance/test_generated_combat.py; apps/agent/tests/test_encounter_builder.py -->

**Key references:**
- *Game Mechanics Bestiary — Loot Tables*
- *Game Mechanics Bestiary — Harvesting System*
- *Game Mechanics Bestiary — Encounter Builder*
- *Game Mechanics Crafting — Material Sources (Phase 5 link)*
