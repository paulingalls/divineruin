# Phase 7 — Bestiary Audit (Sprint-003)

> Source: `docs/game_mechanics/game_mechanics_bestiary.md` (1234L) vs `docs/milestones/07_bestiary.md` (41 acceptance items across M7.1–M7.4). Read-only. Status legend: **confirmed** (symbol + tests exist and match spec), **partial** (something ships but scope/shape diverges), **aspirational** (spec symbol/feature missing or renamed without a wrapper), **divergent** (shipped artifact contradicts spec), **NOT_SHIPPED** (no implementation found), **NEW** (spec content with no corresponding milestone item).

## Summary

| Section | Confirmed | Partial | NOT_SHIPPED |
| --- | --- | --- | --- |
| M7.1 — Creature Stat Block Schema | 0 | 0 | 9 |
| M7.2 — Regional Creature Catalog | 0 | 1 | 10 |
| M7.3 — Hollow Creatures (Special Mechanics) | 0 | 0 | 10 |
| M7.4 — Loot, Harvesting & Encounter Builder | 0 | 0 | 11 |

**Headline finding:** The Phase 7 bestiary is unshipped at the data and schema layers. There is no `content/creatures.json`, no `creatures` DB table, no `validate_creature_stat_block`, and no agent tool family for creatures, loot, harvesting, or encounter generation. The only shipped artifact in scope is `content/encounter_templates.json` (6 hand-authored encounters) plus `db_content_queries.get_encounter_template()` / `combat_init.start_combat()` which consume those templates — but they use a flat enemy schema (`id, name, level, ac, hp, attributes, action_pool, xp_value, sound_signature`) that is **not** the M7.1 universal stat block. No `hollow` nested fields, no `behavior`, no `narration`, no `audio` sub-objects, no `loot`, no `passives/actives/reactions`, no `category`, no `tier`, no `save_proficiencies`. The capstone (story-004) should uncheck every acceptance box across all four milestones.

**Bestiary-specific gap (spec vs milestone):** M7.2 deliverable text claims "38+ natural creatures" and "humanoid enemies including Ashmark Soldier, Cult Acolyte." The spec authors **19 natural creatures** (4 Greyvale + 2 Thornveld + 2 Drathian Steppe + 3 Keldaran + 2 Sunward + 2 Underground + 4 Multi-Region) and does **not** include Ashmark Soldier or Cult Acolyte stat blocks. The "38+" claim is undershipped by the spec itself, before any code is written. Capstone should reconcile by either authoring the missing 19+ creatures (spec change) or tightening the milestone text to "19+ natural creatures." Ashmark Soldier and Cult Acolyte are referenced in lore and prompts (`docs/world_data_simulation.md`, `apps/agent/creation_prompts.py`) but have no stat blocks anywhere.

Naming caveats (forward notes — none of these symbols exist yet):
- `validate_creature_stat_block(creature)` — not in `apps/agent/`. The encounter-template path validates "has enemies > 0" only (`apps/agent/tests/test_content_validation.py:109-112`).
- `query_creatures_by_region(region_id, tier_filter)` — not present. The closest neighbor is `get_encounter_template(encounter_id)` at `apps/agent/db_content_queries.py:146`, which is single-id lookup, not region-filtered.
- `query_creature_by_id(creature_id)` — not present.
- `build_encounter(tier, combatant_count, environment)` / `generate_encounter(region, tier, difficulty)` — not present. `start_combat(context, encounter_id, …)` (`apps/agent/combat_init.py:27`) consumes pre-authored templates; it does not generate or compose creatures.
- `generate_loot(creature, player_skills)` — not present.
- `resolve_harvesting(creature_id, player_skills)` — not present. Loot in encounter templates currently flows through `inventory_tools.add_item(…, source="looted", …)` (`apps/agent/inventory_tools.py:28+`) as free-form strings; no creature→loot mapping.
- `apply_corruption_aura(creature, targets, distance)` — not present.
- `resolve_resonance_on_death(creature, nearby_casters)` — not present. The Resonance system itself is NOT_SHIPPED (see sprint-002 `docs/milestones/audit/phase-3-magic.md`).

## Coverage matrix

Every titled subsection of `docs/game_mechanics/game_mechanics_bestiary.md` is mapped below. Items marked NEW are spec content with no corresponding milestone item.

| Spec section (file:line) | Milestone item | Notes |
| --- | --- | --- |
| Creature Stat Block Schema — Schema Definition (bestiary.md:13-115) | M7.1 deliverables 1-6 + DB migration | Canonical schema. `CreatureStatBlock`, nested `Attack`, `Ability`, `LootEntry`. |
| Schema — Hollow nested fields (bestiary.md:48-55) | M7.1 deliverable 2 + acceptance bullet 2 | `class | corruption_aura | resonance_on_death | veil_effect | vulnerable_to`. |
| Schema — `behavior` (tactics/morale/group_size/environment) (bestiary.md:57-63) | M7.1 deliverable 3 ("Behavior fields: aggression pattern, retreat threshold, group tactics") | Spec key names diverge from milestone wording: spec uses `tactics`, `morale`, `group_size`, `environment`; milestone uses "aggression pattern", "retreat threshold", "group tactics". Capstone should harmonize. |
| Schema — `narration` 5-field cue pack (bestiary.md:65-72) | M7.1 deliverable 4 ("appearance_cue, combat_cue, death_cue") | Spec lists **5** narration fields: `first_sighting`, `attack_cue`, `wounded_cue`, `death_cue`, `ambient_cue`. Milestone names only 3. Capstone should widen milestone to spec. |
| Schema — `audio` 4-field + special map (bestiary.md:74-81) | M7.1 deliverable 5 ("ambient_sound, attack_sound, death_sound") | Spec lists `ambient`, `attack`, `hit`, `death`, `special: dict`. Milestone misses `hit` and `special`. |
| Schema — `loot.guaranteed[] / chance[] / hollow_residue` (bestiary.md:83-88) | M7.1 deliverable 6 | OK in shape. Spec uses `hollow_residue: bool`; milestone says "hollow_residue_flag". |
| Schema — `LootEntry.requires_skill: str | None` (bestiary.md:114) | M7.4 acceptance bullets 2-3 | Per-entry skill gate, not a separate harvesting subsystem. |
| Tier System (bestiary.md:117-124) | M7.1 deliverable 7 | Spec maps Tier 3 → L9-14 (not L9-13 as the milestone deliverable says) and Tier 4 → L15-20 (not L14-20). **Divergence — capstone must reconcile.** |
| Encounter Math Guidelines table (bestiary.md:126-135) | NEW | HP/AC/damage-per-round/XP ranges per tier. No M7.x bullet — design-time guidance for content authors. |
| Hollow Combat Properties (bestiary.md:143-150) | NEW | Shared rules across all 9 Hollow: immune to Charmed/Frightened/Poisoned, immune to poison damage, vulnerable to radiant/blessed/Turn Hollow, no death saves, ambient suppression. Not enumerated as M7.3 acceptance items but referenced by M7.3 deliverable 2. |
| Shadeling — Hollow Drift T1 (bestiary.md:154-194) | M7.3 deliverables 1-2 | Full stat block including `hollow` fields, behavior, narration, audio, loot. |
| Hollowmoth — Hollow Drift T1 (bestiary.md:196-237) | M7.3 deliverables 1-2 | Full block. **No loot** (intentional — moths leave nothing). |
| Mawling — Hollow Rend T2 (bestiary.md:241-287) | M7.3 deliverables 1-2 | Full block. |
| Hollow Weaver — Hollow Rend T2 (bestiary.md:291-335) | M7.3 deliverables 1-2 | Full block. Includes `Rearrange (1/round)` and `Spatial Fold` actives — environmental rewriting. |
| Hollowed Knight — Hollow Wrack T3 (bestiary.md:339-388) | M7.3 deliverables 1-3 (boss-tier) | Full block. Mid-game boss with multi-phase mechanics (`Unholy Fortitude`, `Dissolution Strike`). |
| Veilrender — Hollow Wrack T3 (bestiary.md:392-443) | M7.3 deliverables 1-3 (boss-tier) | Full block. Includes `Absorb Magic` reaction + permanent 60ft corruption field. |
| The Choir — Hollow Named T4 (bestiary.md:447-498) | M7.3 deliverable 3 (Tier 4 boss) + acceptance bullet 5 | Spec implements via Resonance Core, 200-yard zone, Stolen Melody (NPC-voice charm), Silence Void, Harmonic Shield reaction. **Resonance on death: 5** — not in milestone. |
| The Still — Hollow Named T4 (bestiary.md:502-550) | M7.3 deliverable 3 + acceptance bullet 6 | Zone Entity with 6 anchors (40-45 HP each, AC 20). Passive-until-attacked. **Resonance on death: 6.** Spec adds "Gentle Absorption" (1d4 attribute drain/day on Charmed targets) — fully outside the standard combat loop. |
| The Architect — Hollow Named T4 (bestiary.md:554-612) | M7.3 deliverable 3 + acceptance bullet 7 | Includes **Legendary Actions (3/round)** and **Legendary Resistance (3/day)** — not mentioned in M7.x. **Resonance on death: 8.** Terrain manipulation (`Reshape`, `Entomb`, `Cathedral`, `Summon Constructs`, `Reactive Architecture`). |
| Grey Wolf — Beast T1 (bestiary.md:624-645) | M7.2 deliverable Greyvale | Stat block + 3 loot rows. **No narration/audio sub-objects** on natural creatures — spec authors them abbreviated vs Hollow. **Schema drift within spec.** |
| Wild Boar — Beast T1 (bestiary.md:649-670) | M7.2 deliverable Greyvale | Same abbreviated form. |
| Giant Spider — Beast T1 (bestiary.md:674-696) | M7.2 deliverable Greyvale | Same. |
| Bandit — Humanoid T1 (bestiary.md:700-724) | M7.2 deliverable Greyvale + "Humanoid enemies" line | Equipment-based loot (Short Sword, Light Crossbow, Leather Armor). |
| Thornveld Stalker — Beast T1 (bestiary.md:732-753) | M7.2 deliverable Thornveld | OK. |
| Corrupted Treant — Elemental T2 (bestiary.md:757-780) | M7.2 deliverable Thornveld | Only "elemental"-category creature in the catalog. Validates the Elemental category branch of M7.1. |
| Steppe Razorwing — Beast T1 (bestiary.md:788-809) | M7.2 deliverable Drathian Steppe | OK. |
| Steppe Bison — Beast T1 (bestiary.md:813-834) | M7.2 deliverable Drathian Steppe | OK. |
| Rock Viper — Beast T1 (bestiary.md:842-862) | M7.2 deliverable Keldaran Mountains | OK. |
| Cave Wyrm — Beast T2 (bestiary.md:866-891) | M7.2 deliverable Keldaran Mountains | OK. |
| War Golem — Construct T3 (bestiary.md:895-918) | M7.2 deliverable Keldaran Mountains + acceptance bullet 4 ("Keldaran include Tier 3") | Only Construct-category natural creature. T3 — satisfies the "late-game region" bullet. |
| Saltmarsh Lurker — Beast T1 (bestiary.md:926-947) | M7.2 deliverable Sunward Coast & Wetlands | OK. |
| Tidecaller Eel — Beast T2 (bestiary.md:951-973) | M7.2 deliverable Sunward Coast & Wetlands | OK. |
| Umbral Crawler — Beast T2 (bestiary.md:981-1004) | M7.2 deliverable Underground | OK. |
| Deepstone Guardian — Construct T2 (bestiary.md:1008-1031) | M7.2 deliverable Underground | OK. |
| Dire Bear — Beast T2 (bestiary.md:1039-1064) | NEW (Multi-Region) | Milestone deliverable lists 6 regions; spec adds a "Multi-Region Threats" 7th group with 4 creatures (Dire Bear, Troll, Bandit Captain, Thunderbird). |
| Troll — Humanoid T2 (bestiary.md:1068-1091) | NEW (Multi-Region) | Regeneration mechanic + fire/acid suppression. |
| Bandit Captain — Humanoid T2 (bestiary.md:1095-1121) | NEW (Multi-Region) | Captures the M7.2 "humanoid leadership" archetype that Ashmark Soldier and Cult Acolyte (named in milestone) would have filled. |
| Thunderbird — Beast T3 (bestiary.md:1125-1150) | NEW (Multi-Region) | Tier 3 — second T3 natural creature in the catalog (besides War Golem). |
| Material Categories table (bestiary.md:1156-1169) | NEW | 10 material categories (hides, bones, organs, metals, wood, cloth, gems, hollow residue, divine, arcane) with source/tier/crafts-into. No M7.x bullet — cross-doc dep with `game_mechanics_crafting.md`. |
| Hollow Residue Tiers (bestiary.md:1171-1178) | M7.3 deliverables (hollow loot) + M7.4 deliverable "Hollow loot tainting" | 4-tier mapping Drift/Rend/Wrack/Named → residue items → uses. Not enumerated in M7.x acceptance. |
| Harvesting Skill Requirements (bestiary.md:1180-1190) | M7.4 deliverable "Skill-gated harvesting tiers" + acceptance bullets 2-3 | Spec defines **7 rows** (None, Survival:Trained, Survival:Expert, Crafting:Trained, Crafting:Expert, Arcana:Trained, Arcana:Expert). Milestone names only 3 tiers (Survival:Trained, Crafting:Expert, Arcana:Expert). **Spec is wider — capstone should widen milestone.** |
| Tainted Material Rules (bestiary.md:1192-1198) | M7.4 deliverables "Hollow loot tainting" + "Purification paths" + acceptance bullet 5 | Spec specifies the corruption-risk effects (passive +1 Resonance/encounter, +25% Hollow encounters, -1 durability/session) — milestone deliverable says "flagged tainted by default" without effect detail. Spec also names purification paths: Dispel Corruption (3 Focus, immediate, Cleric) vs Artificer process (3 async Training cycles). |
| Encounter Building — Solo Player Scaling (bestiary.md:1203-1213) | M7.4 deliverable "Solo player HP math" + acceptance bullets 6-7 | Spec gives a 5-row level-bracketed scaling table (L1-2 through L15-20). Milestone has "1 player + companion at 75% effectiveness" but doesn't enumerate the level brackets. |
| Companion Scaling — 75% effectiveness (bestiary.md:1215-1217) | M7.4 acceptance bullet 7 | Encoded as design rule, not as a constant. Companion math in `hp_scaling.py` is unrelated to this — capstone should confirm 75% effectiveness is the intended companion combat-math anchor. |
| Environment Modifiers table (bestiary.md:1219-1228) | M7.4 deliverable "Environment modifiers" + acceptance bullet 8 | 6 modifier rows: Hollow corruption (light/heavy), Natural terrain, Urban/indoor, Night, Sacred site. Not enumerated in M7.x acceptance. **Cross-cut with M3.x Resonance — three rows alter Resonance generation.** |
| Design Decisions Log pointer (bestiary.md:1232-1234) | NEW | Decisions 24-29 in `game_mechanics_decisions.md`. Pointer only. |

## M7.1 — Creature Stat Block Schema

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| Schema supports all 6 creature categories with shared base fields | No `CreatureStatBlock` symbol in `apps/agent/` or `packages/shared/`. `rg -i "creaturestatblock|class\s+Creature"` → 0 matches. The encounter-template enemy dict (`content/encounter_templates.json:8-33`) has `id, name, level, ac, hp, attributes, action_pool, xp_value, sound_signature` — **no `category` field, no `tier` field, no `save_proficiencies`, no nested `behavior`, no nested `narration`, no nested `loot`**. | None | NOT_SHIPPED |
| Hollow-specific nested fields are optional and only validated when category is "hollow" | No `category` field exists in the encounter-template enemy schema. No `hollow` nested object. No validator distinguishes Hollow from non-Hollow at the data layer. | None | NOT_SHIPPED |
| All attack entries include name, attribute, damage_dice, damage_type, range, and optional effects | `action_pool` entries (`encounter_templates.json:22-29`) have `name, damage, damage_type, properties, description`. Missing: `type` (melee/ranged/area), `reach`, `to_hit`, `special`, `audio` — versus spec `Attack` class at `bestiary.md:93-101`. **Schema drift.** | None | NOT_SHIPPED (the spec-shaped `Attack` is not implemented). |
| Tier system correctly maps tiers 1-4 to player level ranges | No `tier` field anywhere in code. **Spec/milestone divergence on Tier 3 boundary:** spec at `bestiary.md:121-124` says Tier 3 = L9-14 and Tier 4 = L15-20; milestone deliverable 7 says Tier 3 = L9-13 and Tier 4 = L14-20. Capstone must reconcile. | None | NOT_SHIPPED |
| Narration fields provide audio-first cues (sound/smell before sight) | No `narration` field on encounter-template enemies. Hollow creature narration in the spec (`bestiary.md:180-186, 226-230, etc.`) is fully written but unwired. Natural creature narration is **not authored in the spec** — only Hollow creatures have narration cue blocks. **Spec-internal coverage gap: 9/28 creatures (the Hollow set) have narration; 19/28 (natural) do not.** | None | NOT_SHIPPED |
| Loot schema supports both guaranteed and probabilistic drops | No `loot` field on encounter-template enemies. Loot in code today flows through `inventory_tools.add_item(..., source="looted", ...)` (`apps/agent/inventory_tools.py:28+`) as free-form DM-narrated strings — no creature→loot mapping, no probability roll, no guaranteed-vs-chance split. | None | NOT_SHIPPED |
| `validate_creature_stat_block` rejects invalid entries with specific error messages | No symbol `validate_creature_stat_block`. `rg "validate_creature"` → 0 matches. The only content validation is `tests/test_content_validation.py:109-112` which checks "encounter has ≥1 enemy" — does not validate schema shape. | None | NOT_SHIPPED |
| DB migration runs cleanly with proper indexes on category, tier, and name | No `creatures` table. Migration 001 (`scripts/migrations/001_initial_schema.sql:75-82`) creates `encounter_templates` (JSONB by id), and migration 002 (`scripts/migrations/002_add_indexes.sql`) does not index any creature-shaped data. Migrations 003-017 are inventoried; none introduce `creatures`. | None | NOT_SHIPPED |
| Tests cover validation for all 6 categories including Hollow edge cases | No `test_creature*.py` or `test_bestiary*.py` file in `apps/agent/tests/`. | None | NOT_SHIPPED |

**Deliverables status:**
- Universal `CreatureStatBlock` (id, name, category, tier, level, hp, ac, speed, attributes, save_proficiencies, attacks[], multiattack, passives, actives, reactions): NOT_SHIPPED.
- Hollow nested object (`class | corruption_aura | resonance_on_death | veil_effect | vulnerable_to`): NOT_SHIPPED.
- Behavior fields (spec key names `tactics, morale, group_size, environment` vs milestone wording "aggression pattern / retreat threshold / group tactics"): NOT_SHIPPED + **wording divergence to harmonize**.
- Narration 5-field block (spec) vs 3-field block (milestone): NOT_SHIPPED + **milestone undercommits — 5 fields in spec, 3 named in milestone**.
- Audio 4-field + `special: dict` (spec) vs 3-field (milestone): NOT_SHIPPED + **milestone undercommits**.
- Loot schema (guaranteed[] / chance[] / hollow_residue): NOT_SHIPPED.
- `xp_reward`: NOT_SHIPPED at schema level (XP **values** exist inside the encounter-template enemy entries as `xp_value` — a different field name, no validator).
- Tier system constants T1=L1-4 / T2=L5-8 / T3=L9-13(?) / T4=L14-20(?) — **divergent between spec and milestone**; NOT_SHIPPED in code.
- DB migration `creatures` table + indexes on category/tier/name: NOT_SHIPPED.
- `validate_creature_stat_block(creature)`: NOT_SHIPPED.

## M7.2 — Regional Creature Catalog

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| All 38+ creatures have complete stat blocks passing M7.1 validation | **The spec itself authors only 19 natural creatures**, not 38+. `grep -c "^#### " bestiary.md` → 19 (Grey Wolf through Thunderbird). Adding the 9 Hollow gives 28 total — still short of 38. **M7.2 deliverable text is aspirational vs spec content.** Beyond the count, none of the creatures are encoded in `content/creatures.json` (file does not exist). | None | NOT_SHIPPED |
| Every region has at least 3 creatures spanning appropriate tiers | Spec coverage per region: Greyvale 4, Thornveld 2, Drathian Steppe 2, Keldaran 3, Sunward 2, Underground 2, Multi-Region 4. **Thornveld, Drathian Steppe, Sunward, and Underground have only 2 creatures each — fails the ≥3 rule at the spec level.** Multi-Region (4) helps but is a new 7th group. | None | NOT_SHIPPED (and spec content underdelivers vs the rule) |
| Greyvale creatures are Tier 1 only (starter region) | Spec authors only Tier 1 creatures in Greyvale (Grey Wolf L1, Wild Boar L1, Giant Spider L2, Bandit L2). Bandit and Spider are level 2 but still Tier 1. Satisfies rule **at spec level**; NOT_SHIPPED in data. | None | NOT_SHIPPED (spec OK) |
| Keldaran Mountains include Tier 3 creatures (late-game region) | Spec: War Golem L10 T3 (`bestiary.md:895`). Satisfies rule **at spec level**. NOT_SHIPPED in data. | None | NOT_SHIPPED (spec OK) |
| Each creature has distinct behavior pattern and retreat threshold | Spec authors a `Behavior:` line + `Morale:` line per creature (e.g., `bestiary.md:636-637`). Coverage looks complete at the spec level for all 28 creatures. NOT_SHIPPED in data — no enforcement, no validator. | None | NOT_SHIPPED (spec OK) |
| Narration cues follow audio-first convention (sensory details, not visual descriptions) | **Spec drift:** Hollow creatures (9/28) have full 5-field narration blocks. Natural creatures (19/28) have **no narration block at all** — only a `Behavior:` line. The audio-first cue requirement cannot be met for natural creatures from the current spec. **Spec must be widened to include narration on natural creatures, or milestone must restrict to "Hollow narration cues."** | None | NOT_SHIPPED + **spec content gap on natural creatures**. |
| Humanoid enemies have equipment-based attacks matching their role | Spec authors Bandit (`bestiary.md:700-724`: Short Sword + Light Crossbow + Dirty Fighting), Troll (`bestiary.md:1068-1091`: claws/bite + Regeneration), Bandit Captain (`bestiary.md:1095-1121`: Longsword/Heavy Crossbow + Leadership). **Ashmark Soldier and Cult Acolyte (named in milestone deliverable text) are NOT in the spec.** Capstone should either author these or strike from milestone. | None | NOT_SHIPPED + **2 named humanoids absent from spec**. |
| `query_creatures_by_region` filters correctly by region and tier | No symbol `query_creatures_by_region`. `rg "query_creatures"` → 0 matches in `apps/agent/`. | None | NOT_SHIPPED |
| `query_creature_by_id` returns null/error for nonexistent IDs | No symbol `query_creature_by_id`. The neighbor `get_encounter_template(encounter_id)` at `apps/agent/db_content_queries.py:146-153` returns the encounter envelope (not a creature) and returns `None` on miss — same shape M7.2 would want, but operates on encounters, not creatures. | None | NOT_SHIPPED |
| `content/creatures.json` passes schema validation for all entries | **File does not exist.** `ls content/` yields: encounter_templates, events, factions, gods, inventory_pools, items, level_progression, locations, lore_entries, npc_state, npcs, players, quests, scenes, training_activity_types, training_programs, voice_registry, npcs. No creatures.json. | None | NOT_SHIPPED |
| Tests verify creature distribution across regions and tier balance | None present. The closest neighbor is `tests/test_content_validation.py:109-127` which validates encounter-template integrity. | None | NOT_SHIPPED |

**Partial: encounter-template enemy data is the only shipped artifact.** `content/encounter_templates.json` (6 templates: shadeling_cluster, ruins_mawling_pair, hollowed_scout, hollow_wisp, hollow_patrol_greyvale, ruins_guardian) ships abbreviated stat blocks for embedded Hollow and proto-creatures. These are **not** the M7.2 catalog — they are pre-baked encounter compositions consumed by `start_combat(encounter_id)`. Counts: 6 encounter templates, ~14 unique enemy entries when deduplicated. No regional creatures (Grey Wolf, Wild Boar, etc.) appear in this file.

**Deliverables status:**
- 38+ creature catalog in `content/creatures.json`: NOT_SHIPPED. **Spec authors only 19 natural + 9 Hollow = 28; milestone target is aspirational.**
- Per-creature stat block + 1-3 attacks + behavior pattern + retreat condition + narration cues + audio hints: NOT_SHIPPED. **Natural creatures in spec lack narration & audio sub-objects.**
- Humanoid enemies with equipment-based attacks: spec partial (Bandit, Bandit Captain, Troll authored; Ashmark Soldier, Cult Acolyte absent).
- `content/creatures.json` organized by region: NOT_SHIPPED.
- Agent tools `query_creatures_by_region`, `query_creature_by_id`: NOT_SHIPPED.

## M7.3 — Hollow Creatures (Special Mechanics)

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| All 9 Hollow creatures have complete stat blocks with hollow nested fields populated | Spec ships all 9 (Shadeling, Hollowmoth, Mawling, Hollow Weaver, Hollowed Knight, Veilrender, The Choir, The Still, The Architect — `bestiary.md:154-612`). **Hollow nested fields are fully authored in spec** (class, aura radius, resonance_on_death, veil_effect, vulnerabilities). NOT_SHIPPED in data — `content/creatures.json` does not exist. `content/encounter_templates.json` includes `shadeling_*`, `mawling_*`, and `hollow_*` enemy entries but with the abbreviated encounter-template enemy schema (no `hollow:{}` nested object). | None | NOT_SHIPPED |
| Corruption aura applies correctly based on distance and target saves | No `apply_corruption_aura` symbol. `rg "corruption_aura"` against `apps/` → 0 matches. Spec auras: Shadeling 0ft (contact), Mawling 5ft, Weaver 30ft (spatial), Hollowed Knight 10ft, Veilrender 60ft permanent corruption field, Choir 200yd Aura of Lost Voices, Still ~1mi zone, Architect ~0.5mi construction zone. None mechanically wired. | None | NOT_SHIPPED |
| `resolve_resonance_on_death` feeds correct Resonance deltas to nearby casters | No symbol `resolve_resonance_on_death`. The Resonance system itself is NOT_SHIPPED (see sprint-002 audit `docs/milestones/audit/phase-3-magic.md`). Spec values: Shadeling 0 / Hollowmoth 0 / Mawling 1 / Weaver 1 / Knight 2 / Veilrender 3 / Choir 5 / Still 6 / Architect 8. | None | NOT_SHIPPED |
| Each Hollow creature has a distinct veil_effect and vulnerability | Spec authors all 9 veil_effects (e.g., Shadeling "ambient sounds thin in 10ft, birdsong stops"; Architect "construction sounds from no tool"). All vulnerable_to lists are populated. **Spec OK; NOT_SHIPPED in data.** | None | NOT_SHIPPED |
| The Choir has custom multi-phase audio-zone combat behavior (not standard attack loop) | Spec authors the Resonance Core (DC 18 Perception/Arcana to locate), Aura of Lost Voices (200yd), Memory Scream, Stolen Melody (NPC-voice charm), Cacophony, Silence Void, Harmonic Shield reaction (`bestiary.md:447-498`). No code path implements any of this — `combat_init.py` runs flat initiative + per-turn attacks against any enemy uniformly. | None | NOT_SHIPPED |
| The Still has passive-until-attacked behavior with damage reflection | Spec authors Zone Entity (6 anchors @ 40-45 HP / AC 20 each), Paradise Trap (WIS DC 18 unwilling-to-leave), Gentle Absorption (1d4 attribute drain/day), Illusory Perfection, Rejection (teleports attackers to zone edge), Final Stillness (`bestiary.md:502-550`). **Spec does NOT implement "damage reflection" verbatim** — the closest match is Rejection (ejection, not reflection). **Milestone acceptance bullet 6 ("damage reflection") diverges from spec** — capstone should reconcile to "ejection / forced disengage." NOT_SHIPPED in code. | None | NOT_SHIPPED + **milestone/spec divergence on the "damage reflection" mechanic** |
| The Architect has terrain manipulation abilities that alter combat grid state | Spec authors Architect's Domain (~0.5mi construction zone, terrain reshapes each round), Incorporeal Movement, Legendary Resistance (3/day), Reshape (1/round, free action — wall/floor/ceiling section ≤20×20ft within 120ft), Entomb (Recharge 5-6), Cathedral (1/encounter — 60ft radius impossible-geometry structure), Summon Constructs (1/encounter — 2d4 minions), Reactive Architecture reaction, **Legendary Actions (Shift Wall / Geometry Strike / Reshape, 3/round)** at `bestiary.md:583-586`. No combat-grid system in code: `combat_init.py` does not track grid state; movement is narrated, not gridded. | None | NOT_SHIPPED |
| Tier 1-2 Hollow creatures function as standard combat encounters (no custom behavior needed) | Spec: Shadeling, Hollowmoth, Mawling, Hollow Weaver are T1-T2. Weaver's `Rearrange (1/round)` and `Spatial Fold (Recharge 5-6)` are explicitly non-standard — they manipulate space, not just deal damage. **Milestone acceptance bullet 8 understates Hollow Weaver's complexity** — Weaver is closer to a "miniboss with environmental manipulation" than a "standard combat encounter." Capstone should re-tier Weaver or rewrite the bullet. | None | NOT_SHIPPED + **bullet vs spec mismatch on Hollow Weaver scope** |
| Tier 3 Hollowed Knight and Veilrender have boss-tier HP and multi-phase mechanics | Spec: Knight 85 HP + `Unholy Fortitude` (CON save at 0 HP for 1 HP, escalating DC) + `Command Lesser` (controls minions) + `Dissolution Strike` (Recharge 5-6). Veilrender 120 HP + `Absorb Magic` reaction (heals from incoming spells) + `Reality Crush` + `Corruption Pulse`. Both stat blocks include the multi-phase mechanics. **Spec OK; NOT_SHIPPED in data.** | None | NOT_SHIPPED |
| Tests cover corruption aura at various distances, resonance_on_death, and all 3 Tier 4 custom behaviors | None present. | None | NOT_SHIPPED |

**Deliverables status:**
- 9 Hollow creatures in `content/creatures.json` with hollow-specific fields populated: NOT_SHIPPED. Spec text is complete; data file missing.
- Per-Hollow `corruption_aura (radius, effect, DC)`, `resonance_on_death (int)`, `veil_effect (str)`, `vulnerability (list)`: NOT_SHIPPED.
- Tier 4 custom combat behaviors (Choir audio-zone ambush, Still passive-defensive, Architect terrain manipulation): NOT_SHIPPED. **Architect Legendary Actions/Resistance — NEW vs milestone, not enumerated.**
- Rules engine `apply_corruption_aura(creature, targets, distance)`: NOT_SHIPPED.
- Rules engine `resolve_resonance_on_death(creature, nearby_casters)`: NOT_SHIPPED (also blocked on M3.1 Resonance system being NOT_SHIPPED).

## M7.4 — Loot Tables, Harvesting & Encounter Builder

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| `generate_loot` returns guaranteed drops always and probabilistic drops at correct rates | No symbol `generate_loot`. `rg "generate_loot"` → 0 matches. Loot today is DM-narrated and added via `inventory_tools.add_item(item_id, quantity, source, ...)` with no probability rolls. | None | NOT_SHIPPED |
| Harvesting requires correct skill tier: Survival:Trained, Crafting:Expert, Arcana:Expert | **Spec defines 7 skill rows** (None / Survival:Trained / Survival:Expert / Crafting:Trained / Crafting:Expert / Arcana:Trained / Arcana:Expert — `bestiary.md:1182-1190`), but **milestone names only 3.** Milestone undercommits. NOT_SHIPPED either way. | None | NOT_SHIPPED |
| Player without required skill tier gets no harvesting option (not a failed roll — gated out entirely) | No harvest tool exists. Per-loot-entry `requires_skill` is defined in the spec `LootEntry` schema (`bestiary.md:114`) but no consumer. | None | NOT_SHIPPED |
| All Hollow creature loot is flagged tainted; non-Hollow loot is not | No `tainted` field on any DB schema or content file. `rg "tainted"` in code → one match in `apps/server/src/debug.ts:325`, a debug-tools button label `"Corruption 2 (Tainted)"` that emits a `hollow_corruption_changed` test event — unrelated to loot tainting. Hollow Residue Tiers table at `bestiary.md:1171-1178` defines what tainted Hollow loot looks like, but nothing reads it. | None | NOT_SHIPPED |
| Purification via Dispel Corruption clears taint flag; async purification tracks activity timer | No `Dispel Corruption` spell exists (spell catalog NOT_SHIPPED per Phase 3 audit). No async purification activity in `apps/agent/training_rules.py:22+` (activity types include `spell_cantrip`, `combat_drill`, etc.; no `purification` slug). | None | NOT_SHIPPED |
| `build_encounter` selects creatures matching requested tier and scales to combatant count | No symbol `build_encounter` or `generate_encounter`. The closest neighbor `start_combat(encounter_id)` (`apps/agent/combat_init.py:27`) **looks up a pre-authored template by id** — it does not select, scale, or compose. | None | NOT_SHIPPED |
| Solo encounters assume 1 player + 1 companion at 75% HP effectiveness | The 75% companion-effectiveness rule (`bestiary.md:1217`) is encoded only in spec. Companion HP math lives in `apps/agent/hp_scaling.py` and `apps/agent/companion_idle.py` — neither references a 75%-of-player anchor. The 5-row level-bracketed scaling table (`bestiary.md:1207-1213`) is not enumerated anywhere in code. | None | NOT_SHIPPED |
| Environment modifiers adjust creature selection (e.g., no aquatic creatures in mountains) | Spec authors 6 modifier rows (`bestiary.md:1221-1228`: Hollow corruption light/heavy, Natural terrain, Urban/indoor, Night, Sacred site). No encounter-generation code consumes any of these. Region taxonomy in `apps/agent/region_types.py` defines region constants used elsewhere but is not linked to creature selection. | None | NOT_SHIPPED |
| Generated encounters resolve in 3-5 rounds given expected player damage output | Encounter math reference table at `bestiary.md:128-135` exists. No combat-length test fixture exercises this. Combat resolution paths (`combat_resolution.py`, `combat_turn.py`, `combat_end.py`) don't measure or enforce round-count targets. | None | NOT_SHIPPED |
| Loot materials link to Phase 5 crafting recipes where applicable | Phase 5 (Crafting) is sprint-003 group A. Material Categories table (`bestiary.md:1156-1169`) names crafting outputs per category, but no `material_id → recipe_id` linkage in code. `content/items.json` includes some items by id but no creature→material→recipe pipeline. Cross-doc dep with `docs/game_mechanics/game_mechanics_crafting.md`. | None | NOT_SHIPPED |
| Tests cover loot generation for all creature categories, harvesting skill gates, encounter scaling, and environment filtering | None present. | None | NOT_SHIPPED |

**Deliverables status:**
- `generate_loot(creature, player_skills)`: NOT_SHIPPED.
- Skill-gated harvesting tiers (3 in milestone vs **7 in spec**): NOT_SHIPPED + **milestone undercommits**.
- Hollow loot tainting + tainted flag: NOT_SHIPPED.
- Purification paths (Cleric Dispel Corruption / Artificer async): NOT_SHIPPED. **Spec specifies costs (3 Focus / 3 Training cycles) — milestone deliverable is vaguer.**
- `build_encounter(tier, combatant_count, environment)` / `generate_encounter(region, tier, difficulty)`: NOT_SHIPPED.
- Solo player HP math anchored at 75% companion effectiveness: NOT_SHIPPED.
- Environment modifiers per the 6-row spec table: NOT_SHIPPED.
- 3-5 round resolution target: NOT_SHIPPED (no test fixture, no enforcement).
- Agent tools `resolve_harvesting`, `generate_encounter`: NOT_SHIPPED.

## Material gaps surfaced

1. **Entire M7.1–M7.4 milestone series is unshipped.** Capstone (story-004) should mark Phase 7 as NOT_STARTED in `docs/milestones/07_bestiary.md`. The 41 acceptance boxes are already unchecked — no checkmarks to revert, but the milestone-level "Goal" framings imply ongoing work and should be re-flagged as deferred.

2. **Spec underdelivers the M7.2 creature count.** Milestone says "38+ natural creatures"; spec authors only **19 natural** (4+2+2+3+2+2+4). Spec also lacks **Ashmark Soldier** and **Cult Acolyte** stat blocks even though both are named in `docs/world_data_simulation.md`, `apps/agent/creation_prompts.py`, and the M7.2 deliverable text. Two paths for the capstone:
   - **(A)** Author 19+ additional natural creatures + Ashmark Soldier + Cult Acolyte (spec change).
   - **(B)** Tighten milestone target to "19+ natural creatures (covering 6 regions + multi-region threats)" and strike Ashmark Soldier / Cult Acolyte from the deliverable line.
   Recommended: **(B)**, with Ashmark Soldier / Cult Acolyte authored later as Tier 2 humanoid variants when the Ashmark front-line content arrives.

3. **Tier 3 / Tier 4 level boundary divergence.** Spec at `bestiary.md:121-124`: Tier 3 = L9-14, Tier 4 = L15-20. Milestone deliverable 7 at `07_bestiary.md:23`: Tier 3 = L9-13, Tier 4 = L14-20. Capstone must reconcile — recommend **spec wins** (L9-14 / L15-20) since the spec's Encounter Math Guidelines table at `bestiary.md:130-135` is keyed to those ranges.

4. **Narration block coverage uneven in spec.** All 9 Hollow creatures have full 5-field narration blocks (first_sighting / attack_cue / wounded_cue / death_cue / ambient_cue). All 19 natural creatures have **no narration block** — only a `Behavior:` line. M7.2 acceptance bullet 5 ("Narration cues follow audio-first convention") cannot be satisfied for natural creatures without widening the spec. Capstone should flag the spec gap.

5. **Schema field-name harmonization.** Milestone uses informal field names ("appearance_cue / combat_cue / death_cue", "ambient_sound / attack_sound / death_sound", "hollow_residue_flag", "aggression pattern / retreat threshold / group tactics"). Spec uses code-identifier names (`first_sighting / attack_cue / wounded_cue / death_cue / ambient_cue`, `ambient / attack / hit / death / special`, `hollow_residue: bool`, `tactics / morale / group_size / environment`). Capstone should adopt the spec's names — they are the implementation contract.

6. **Spec scope diffs from milestone in specific bullets:**
   - **The Still — "damage reflection" (M7.3 acceptance 6) vs "Rejection ejection" (spec).** Reconcile in favor of spec — the Still's defense is positional displacement plus illusion intensity, not damage reflection. Recommend rewording milestone bullet to "passive-until-attacked behavior with anchor-based zone defense."
   - **Hollow Weaver — "standard combat encounter" (M7.3 acceptance 8) vs spec's `Rearrange` / `Spatial Fold` mechanics.** Weaver manipulates space; not standard. Recommend re-tagging Weaver as "environmental boss" or rewording the acceptance bullet to exclude Weaver from the "standard" set.
   - **Harvesting tiers — 3 in milestone (Survival:Trained, Crafting:Expert, Arcana:Expert) vs 7 in spec (`bestiary.md:1180-1190`).** Recommend milestone widen to all 7.
   - **Architect Legendary Actions / Legendary Resistance** (`bestiary.md:583, 571`) — not mentioned in M7.3 deliverables or acceptance. These are the "active combat" mechanics that make the Architect the most dangerous bestiary entity. Recommend adding an acceptance bullet.

7. **`content/encounter_templates.json` is the only shipped artifact and uses a divergent enemy schema.** 6 templates, ~14 unique enemy entries, flat fields: `id, name, level, ac, hp, attributes, action_pool, xp_value, sound_signature`. Missing every M7.1 nested object (behavior, narration, audio, loot, hollow). When the M7.1 schema is built, the encounter-template enemies will need either (a) migration to the canonical schema, or (b) a documented "encounter-template enemy" sub-schema that explicitly excludes the rich fields. The current state is **divergent**, not partial — `start_combat` is satisfied by the flat schema and a richer schema would break it without migration code.

8. **Cross-cut with Phase 3 (Magic): every Hollow creature mechanic that touches Resonance is blocked.** `resonance_on_death`, `corruption_aura` interaction with caster Resonance, Hollowed condition (referenced in Hollowed Knight crit at `bestiary.md:351` and Veilrender Corruption Pulse at `bestiary.md:414`), Charmed-immune flag (Hollow Combat Properties at `bestiary.md:145`), and the Resonance state interaction with Veilrender's `Absorb Magic` reaction — all of these depend on the Resonance system, the Hollowed condition, and the spell-Focus tracking from M3.x, all of which are NOT_SHIPPED per `docs/milestones/audit/phase-3-magic.md`.

9. **Cross-cut with Phase 5 (Crafting): material-to-recipe pipeline absent.** Material Categories table (`bestiary.md:1156-1169`) names 10 categories and their crafting outputs. No `materials` content file, no `recipes` content file in `content/`. The "Loot materials link to Phase 5 crafting recipes" acceptance bullet at `07_bestiary.md:155` is unconditionally blocked.

10. **Cross-cut with story-003 (encounter_roles audit, sprint-003 group B).** `docs/game_mechanics/game_mechanics_encounter_roles.md` is referenced as containing creature role/loot/XP modifiers and encounter budget math. This audit does **not** catalog encounter_roles content — story-003 owns it. M7.4's encounter builder (`build_encounter`) will likely want a `role` axis (`docs/INDEX.md` summary line for encounter_roles names: stat / loot / XP modifiers + encounter budget). Capstone should cross-reference both audits when staging Phase 7.

## NEW spec sections without milestone items

| Spec section | Why NEW | Recommendation |
| --- | --- | --- |
| **Encounter Math Guidelines** table (bestiary.md:126-135) | Per-tier HP / AC / damage-per-round / XP ranges. No M7.x bullet references these as inputs to `build_encounter`. | Add an M7.4 deliverable: "Encounter math constants table (HP/AC/DMG/XP per tier) consumed by `build_encounter`." |
| **Hollow Combat Properties** shared list (bestiary.md:143-150) | Immune to Charmed/Frightened/Poisoned + immune to poison damage + vulnerable to radiant/blessed/Turn Hollow + no death saves + audio suppression. M7.3 deliverable 2 references "vulnerability" but does not enumerate the shared immunities. | Add an M7.3 acceptance bullet: "All Hollow creatures share immunities (Charmed/Frightened/Poisoned, poison damage) and vulnerabilities (radiant, blessed weapons, Turn Hollow) inherited by category, not duplicated per creature." |
| **Multi-Region Threats** group (bestiary.md:1035-1150) | Dire Bear, Troll, Bandit Captain, Thunderbird — a 7th region group not enumerated in the M7.2 regional list (which names 6 regions). | Add the 7th group to the M7.2 deliverable list, or document Multi-Region as a "shared pool" rather than a region. |
| **Material Categories** table (bestiary.md:1156-1169) | 10 material categories (hides, bones, organs, metals, wood, cloth, gems, hollow residue, divine, arcane) with source/tier/crafts-into. M7.4 acceptance bullet 9 references "Phase 5 crafting recipes" but does not name the 10 categories. | Cross-doc dep — confirm the 10 categories live in Phase 5 (Crafting). If they live here, add an M7.4 deliverable. |
| **Hollow Residue Tiers** table (bestiary.md:1171-1178) | 4-tier mapping Drift/Rend/Wrack/Named → residue item names → uses. M7.4 mentions "Hollow loot tainting" but does not enumerate the 4 tiers or the residue item names. | Add an M7.4 deliverable: "Hollow Residue Tier table (Drift/Rend/Wrack/Named) seeded from spec with per-tier residue item names." |
| **Tainted Material Rules** corruption effects (bestiary.md:1192-1198) | Three specific effects (passive +1 Resonance/encounter, +25% Hollow encounters, -1 durability/session). M7.4 deliverable says "flagged tainted by default" without specifying effects. | Add an M7.4 acceptance bullet: "Tainted-equipped items apply one of three corruption effects (+1 Resonance/encounter, +25% Hollow encounter rate, -1 durability/session) per design constant." |
| **Architect Legendary Actions** (bestiary.md:583-586) | Shift Wall / Geometry Strike / Reshape, 3/round between other turns. Not in M7.3. | Add an M7.3 acceptance bullet for Architect Legendary Actions. |
| **Architect Legendary Resistance (3/day)** (bestiary.md:571) | 3-use auto-success-on-failed-save. Not in M7.3. | Add an M7.3 acceptance bullet. |
| **The Choir Resonance Core mechanic** (bestiary.md:465) | Destroying the dense sound point destroys the Choir. Find it via DC 18 Perception/Arcana. Not in M7.3 acceptance bullet 5 which only says "multi-phase audio-zone combat behavior." | Add an M7.3 acceptance bullet: "The Choir has a discoverable Resonance Core targetable via Perception/Arcana DC 18." |
| **The Still Zone Entity / 6 anchors** (bestiary.md:517) | Distributes HP across 6 anchors (40-45 HP / AC 20 each). Destroy all 6 to defeat. Not in M7.3 acceptance 6. | Add an M7.3 acceptance bullet: "The Still is a Zone Entity with 6 anchor points; destroying all 6 destroys the Still." |
| **The Still Gentle Absorption** (bestiary.md:519) | 1d4 attribute drain/day on Charmed targets; reaches 0 → absorbed (non-combat horror mechanic). Not in M7.3. | Add an M7.3 acceptance bullet for the slow-absorption mechanic. |
| **The Choir Silence vulnerability** (bestiary.md:476) | Silence effects suppress Choir abilities for 1 round. Not in M7.3 acceptance 5. | Add to the acceptance bullet. |
| **Reactions field** (schema bestiary.md:46, 99-100, used by Veilrender Absorb Magic, Knight none, Choir Harmonic Shield, Architect Reactive Architecture) | Spec includes `reactions: list[Ability]` in the schema. M7.1 deliverable 1 names `passives[], actives[]` but **not `reactions[]`**. | Add `reactions[]` to the M7.1 deliverable schema list. |
| **Per-Ability `recharge` syntax** (bestiary.md:107) | `None | "1/encounter" | "1/round" | "recharge_5_6"`. Not in any milestone bullet. | Add to M7.1 schema deliverable. |
| **Solo Player Scaling level-bracketed table** (bestiary.md:1207-1213) | 5-row level-bracketed encounter scaling (L1-2 / L3-4 / L5-8 / L9-14 / L15-20) × 3 difficulties (Standard / Tough / Boss). Not enumerated in M7.4 acceptance bullets. | Add an M7.4 acceptance bullet: "`build_encounter` outputs match the 5-row × 3-difficulty scaling table at spec bestiary.md:1207-1213." |
| **Companion Scaling — 75% effectiveness** (bestiary.md:1215-1217) | Spec rule. M7.4 acceptance 7 says "1 player + 1 companion at 75% HP effectiveness" but "HP effectiveness" is more specific than spec ("combat effectiveness"). | Reconcile: spec says **combat** effectiveness (broader); milestone says **HP** effectiveness (narrower). Recommend spec wins. |
| **Environment Modifiers table** (bestiary.md:1219-1228) | 6 rows (Hollow corruption light/heavy, Natural terrain, Urban/indoor, Night, Sacred site). M7.4 acceptance 8 names only "no aquatic creatures in mountains" — example, not the 6-row design. | Add an M7.4 acceptance bullet that lists all 6 environment modifier rows as constants. |

## Cross-doc dependencies

- **Bestiary ↔ Magic (Phase 3, sprint-002 audit):** Every Hollow creature's `resonance_on_death` value, every `corruption_aura` interaction with player Resonance, the Hollowed condition (referenced as a status applied by Knight crits and Veilrender Corruption Pulse), the "Resonance is halved" environment modifier under Sacred site (`bestiary.md:1228`), and the Veilrender `Absorb Magic` reaction (heals from incoming spell Focus × 3) all depend on the M3.x Resonance system being shipped. Per `docs/milestones/audit/phase-3-magic.md`, **all M3.x is NOT_SHIPPED**. Capstone should flag M7.3 as **blocked on Phase 3**.

- **Bestiary ↔ Crafting (Phase 5, sprint-003 group A):** Material Categories table (`bestiary.md:1156-1169`) + Hollow Residue Tiers (`bestiary.md:1171-1178`) + Tainted Material Rules (`bestiary.md:1192-1198`) all feed crafting recipes. M7.4 acceptance bullet 9 ("Loot materials link to Phase 5 crafting recipes where applicable") is the explicit link. **Confirm in the sprint-003 group-A capstone whether the material catalog lives in bestiary or in crafting** — currently the spec puts it in bestiary as a "summary" section. Recommend bestiary own the **material types**, crafting own the **recipes that consume them**.

- **Bestiary ↔ Encounter Roles (story-003, sprint-003 group B):** `docs/game_mechanics/game_mechanics_encounter_roles.md` (per `docs/INDEX.md`) defines per-role stat/loot/XP modifiers. M7.4's `build_encounter` will likely take a `role` axis. This audit does **not** catalog encounter_roles content — story-003 owns it. Cross-reference creature roles between the two audits when the capstone composes the Phase 7 + Encounter Roles deliverables.

- **Bestiary ↔ Regions (Phase 6 NPCs, sprint-002 audit):** Region taxonomy lives in `apps/agent/region_types.py` (constants like `REGION_CITY`). Spec region names — Greyvale, Thornveld, Drathian Steppe, Keldaran Mountains, Sunward Coast, Underground — do not all map to `region_types.py` constants. Recommend M7.2 acceptance bullet for `query_creatures_by_region` to pin region IDs to the existing `region_types.py` constants, **not** spec strings.

- **Bestiary ↔ Skills (Phase 1, sprint-001 audit):** Harvesting requires skill tiers (Survival:Trained, Survival:Expert, Crafting:Trained, Crafting:Expert, Arcana:Trained, Arcana:Expert). Skills system is shipped per Phase 1 (skill ability text at `apps/agent/rules_engine.py:175-200+`). `resolve_harvesting` should consume the existing skill-tier lookup. **No blocker here — the skills layer is ready when M7.4 lands.**

- **Bestiary ↔ Combat init / `start_combat` (Phase 1):** The shipped `combat_init.start_combat(encounter_id)` (`apps/agent/combat_init.py:27-99+`) consumes flat-schema enemy entries from `content/encounter_templates.json`. When M7.1 schema lands, **either** (a) migrate the 6 encounter templates to nested-schema enemies + update `combat_init`, **or** (b) keep encounter-template enemies on the flat schema and document the divergence. The flat schema does not break anything today; the gap is purely about future consistency.
