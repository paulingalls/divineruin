# Phase 7: Bestiary & Encounters

> Source doc: `docs/game_mechanics/game_mechanics_bestiary.md`

Defines the full creature catalog, from stat block schema through regional creatures, Hollow special mechanics, and the encounter builder. Provides the DM agent with a complete library of adversaries and the tools to assemble balanced encounters.

## Catalog Cutover Status (Sprint-063)

<!-- see audit/phase-7-bestiary.md and audit/phase-encounter-roles.md -->

**Status: PARTIAL.** The Python and TypeScript validators, queryable `creatures` table, all 9 spec-authored Hollow creatures, all 19 spec-authored natural creatures, eight encounter creature catalog rows, and internal catalog lookups are shipped. The public combat query surfaces Choir search/core facts; the public creature-catalog query, remaining Hollow mechanics, harvesting and generated encounter builder remain open. All ten authored encounters use catalog references with explicit roles and recommended party levels; combat entry expands them into persisted snapshots.

| Section | Confirmed | Partial | NOT_SHIPPED |
| --- | --- | --- | --- |
| M7.1 — Creature Stat Block Schema | 9 | 0 | 0 |
| M7.2 — Regional Creature Catalog | 11 | 0 | 0 |
| M7.3 — Hollow Creatures (Special Mechanics) | 2 | 0 | 8 |
| M7.4 — Loot, Harvesting & Encounter Builder | 5 | 0 | 6 |

**Catalog cutover and inventory refresh:** All ten encounters store catalog references, explicit roles and recommended party levels; combat expands these references into persisted snapshots. The bestiary Combat Effect Inventory records the supported paths and their remaining limits. Social `command` and `accusation` effects carry narrative-only focus/narration, without automatic healing or spell buff dice. Choir Deafened restrictions, Charmed movement, silence and core phases execute through structured combat paths. The Still and Architect remain deferred Named encounters; their terrain, anchors and legendary mechanics remain open. M7.3 remains partial. The live Combat Effect Inventory names each executable, mixed and narrative-only effect.

Material changes publish immediate owner-scoped agent snapshots after commit. HTTP crafting consumption and keep grants return a full committed HTTP snapshot to the initiator. Other devices use authenticated GET /api/inventory on HUD open/resume and every five seconds while foreground with any HUD panel open, independently of voice connectivity. Background, closed HUD and unmount stop polling. Snapshot generation rejects an older pending GET or mutation snapshot after an immediate update; auth transitions invalidate pending responses. A refresh error preserves inventory and displays retry status; the next scheduled poll retries. The five-second cross-device delay is the accepted tradeoff; no room registry or server packet impersonates the agent.

**Material gaps:**
- **M7.1 schema extensions needed for encounter_roles:** the spec's universal stat block still needs optional `role` (Minion/Standard/Elite/Boss/Named) and Boss-only `legendary_actions[]` for the Phase-7 catalog. Optional `signature_ability` now has a typed catalog home; M4.7 already derives roles from authored templates.
- **M7.2 region-count gap (capstone decision `m7-2-creature-count-gap`):** the earlier milestone count claimed "38+ natural creatures" and named Ashmark Soldier and Cult Acolyte. The spec authors **19 natural creatures** (4 Greyvale + 2 Thornveld + 2 Drathian Steppe + 3 Keldaran + 2 Sunward + 2 Underground + 4 Multi-Region). The milestone count now matches the spec. Ashmark Soldier and Ashmark Sergeant ship in `content/encounter_templates.json` (`ashmark_patrol`); Cultist, Cult Fanatic, and Cult Leader ship there in `cult_cell`. Those five and three Hollow encounter enemies now have spec blocks and catalog rows, and their encounter entries now reference those catalog rows. Cult Acolyte still has no block because no encounter uses it. All 19 natural rows ship in the Phase-7 catalog; generated combat awaits builder integration.
- **M7.3 remains partial:** cast-time Hollow auras and death Resonance execute, and the Choir adds turn-start concentration saves. Mawling standard two-strike and elite/boss three-strike multiattack, Dissolution Maw item wear, and source-owned grapple turn-start damage also execute. Fallen damage adds one death-save failure through the shared damage path; a landed melee attack within 5 ft adds two, including queued strikes after an ally falls. Players cap at three failures; companions stabilize at phase wrap. `test_fallen_melee_failures.py` covers persisted distance boundaries, the Hollowed echo, other damage modes and companion stabilization. These do not certify every troop/Tier3 effect or Still/Architect behavior.
- **M7.4 pure builder API:** `build_encounter(catalog, tier, party, environment, difficulty, rng)` selects catalog references with profile-weighted budget and expected-round bounds. Players supply levels; companions supply owner IDs and profile HP factors; environment is already resolved. `mbp-generated-combat` owns DM entry integration and final M7.4 reconciliation. Combat entry still consumes authored templates.

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
- Optional combat fields: attacks may carry `properties[]`, condition/save fields, `escape_dc`, structured `recharge`, boolean `advantage`, and positive integer `duration`. Typed actives distinguish attacks, direct `healing` and `prepare_attack` from social `command`/`accusation`; untyped actives remain narrative. Present catalog signatures require `name`, `description`, and nonblank sound-first `narration_cue`. Both authored signatures now preserve matching cues and mechanics through seed/query. See the bestiary Combat Effect Inventory for every selected species' supported, scheduled, duplicate and deferred effect. Combat executes the supported attack, healing, preparation and limited-use paths; catalog expansion exposes their IDs and authored cues to the DM. All ten templates now use catalog references. Rows without optional extensions remain valid.

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
- [x] Internal function `query_creatures_by_region` filters correctly by region and tier <!-- verified apps/agent/tests/acceptance/test_creature_catalog.py::test_internal_catalog_queries_use_regions_tier_and_named_missing_error -->
- [x] Internal function `query_creature_by_id` raises on nonexistent IDs <!-- verified apps/agent/tests/acceptance/test_creature_catalog.py::test_internal_catalog_queries_use_regions_tier_and_named_missing_error -->
- [x] `content/creatures.json` passes schema validation for all entries <!-- verified packages/shared/src/entities/creature.test.ts::real_catalog_and_injected_invalid_entry; apps/agent/tests/acceptance/test_creature_catalog.py::test_catalog_columns_and_indexes -->
- [x] Tests verify exact natural creature distribution, Greyvale home tiers, and Keldaran Tier 3 presence <!-- verified apps/agent/tests/test_creature_distribution.py::test_natural_creature_distribution -->

All 19 spec-authored natural catalog rows ship, including the underground pair and four multi-region threats. Their linked loot tables retain every representable spec quantity and harvest requirement. Greyvale's four home-region rows are Tier 1; War Golem gives Keldaran a Tier 3 home row. Bandit and Bandit Captain use their spec equipment attacks; the Troll uses Claw and Bite. The Captain's catalog table uses chain shirt, quality longsword, and map or intel, and catalog-backed encounter captains use that table. Coin pouches and variable stolen goods are omitted because the item-drop schema cannot represent them.

An attack's rider poison damage stays in `special`, while `damage` records its base hit (Giant Spider and Rock Viper). The single `speed` field holds walking speed; Crawler climb 30 ft and Thunderbird fly 80 ft, like earlier climb, burrow, and swim speeds, remain in ability descriptions. Tier 3 `cave_wyrm_scales` can drop from the Tier 2 Cave Wyrm because material tier and creature tier have separate meanings. Guardian Pulse and Lightning Breath use `type: area` with schema-required unused `to_hit: 0`; their saves and areas remain in `special`. Dire Bear's Maul also carries `to_hit: 0`; its auto-hit against grappled targets lives in `special`.

**DM surface:** `query_info(kind="combat")` surfaces Choir search and core facts (`apps/agent/tests/acceptance/test_choir_encounter.py`). Creature catalog lookups remain internal; `query_info(kind="creature")` is still open.

**Key references:**
- *Game Mechanics Bestiary — Regional Creatures*
- *Game Mechanics Bestiary — Creature Behavior Patterns*
- *Game Mechanics Bestiary — Humanoid Enemies*

---

### Milestone 7.3 — Hollow Creatures (Special Mechanics)

**Goal:** Implement the 9 Hollow creatures with unique combat mechanics that break standard patterns, including corruption auras, resonance interactions, and the 3 Tier 4 boss creatures with custom behavior systems.

**Inputs:** M7.1 (creature stat block schema with Hollow extensions), Phase 3 (Magic — Resonance system for resonance_on_death interaction).

The catalog includes all nine spec Hollow creatures, including the three Tier 4 Named. The Still's "1 per anchor" shard and "varies" memories are omitted because the loot quantity schema cannot represent them. The Choir has a Search/Exposed/Destroyed core, DC18 sound search, turn-start DC15 concentration aura, one real-cast Harmonic Shield redirect, three-round Silence Void, structured Deafened, and death Resonance. Focused mechanics evidence is `apps/agent/tests/acceptance/test_choir_encounter.py` and `test_choir_action_contract.py`; native encounter certification remains pending. Still Charmed, anchors, terrain, legendary rules and remaining troop/Tier3 effects remain open. Fictional silence and Deafened restrict legal actions but keep the microphone command path active (`test_voice_condition_commands.py`). The Hollowed Knight encounter uses its catalog loot table. Mawling's Lunge carries structured recharge, advantage, and grapple fields into combat.

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
- [ ] Corruption aura applies correctly based on distance and target saves
- [ ] `resolve_resonance_on_death` feeds correct Resonance deltas to nearby casters
- [x] Each Hollow creature has a distinct veil_effect and vulnerability <!-- verified apps/agent/tests/test_hollow_catalog.py::test_all_hollow_veil_effects_and_vulnerabilities_are_pairwise_distinct -->
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
- Agent catalog reads: `query_info(kind="creature", target_id=None)` returns a creature summary by id, or lists the session region at the party tier. Harvesting runs automatically with victory loot generation at combat end.

**Acceptance criteria:**
- [x] `generate_loot` returns guaranteed drops always and probabilistic drops at correct rates
- [x] Harvesting requires the correct skill tier per the spec's Harvesting Skill Requirements table: every gated drop's kind maps to one spec pair
- [x] Party without a required skill tier gets no harvesting drop (gated out before rolling)
- [x] All Hollow creature loot is flagged tainted; non-Hollow loot is not
- [ ] Purification via Dispel Corruption clears taint flag; async purification tracks activity timer
- [ ] `build_encounter` selects creatures matching requested tier and scales to combatant count
- [ ] Solo encounters use the active companion's profile factor (Kael/Lira/Tam 0.75; Sable 0.50) for budget and expected damage
- [ ] Environment modifiers adjust creature selection (e.g., no aquatic creatures in mountains)
- [ ] Generated encounters resolve in their difficulty's round window given expected player damage output (standard 3-5, tough 4-6, boss 5-7)
- [x] Every loot item is named by a Phase 5 recipe material or marked `crafting_use: "trade"` on its unique catalog owner
- [ ] Tests cover loot generation for all creature categories, harvesting skill gates, encounter scaling, and environment filtering

**Key references:**
- *Game Mechanics Bestiary — Loot Tables*
- *Game Mechanics Bestiary — Harvesting System*
- *Game Mechanics Bestiary — Encounter Builder*
- *Game Mechanics Crafting — Material Sources (Phase 5 link)*
