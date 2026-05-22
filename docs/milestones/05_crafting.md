# Phase 5: Crafting System

> Source doc: `docs/game_mechanics/game_mechanics_crafting.md`

Implements the full crafting pipeline from recipe acquisition through workspace access, crafting resolution with quality outcomes, and item durability. Depends on Phase 1 (Core Systems) for skill tiers. Can run in parallel with Phases 2-4.

---

### Milestone 5.1 — Recipe & Material System

**Goal:** Build the recipe and material data layer with tier-limited recipe slot capacity, three acquisition tracks, and a material catalog that supports substitution and tier minimums.

**Inputs:** Phase 1 M1.2 (skill tiers for recipe slot limits), Phase 1 M1.5 (async training for recipe learning cycles).

**Deliverables:**
- Recipe schema: `id`, `name`, `category`, `tier`, `materials` (with quantities, tier minimums, substitutable flag), `workspace_required`, `crafting_dc`, `time`, `async_cycles`, `output_item`, `study_cost`, `discovery_sources`, `narration_cues`
- Material schema within recipes: `material_id`, `quantity`, `tier_minimum`, `substitutable` flag
- 3 recipe acquisition tracks:
  - Recipe Slots: tier-limited capacity (skill tier determines max slots per recipe tier)
  - Training: 1-6 async cycles via the training system (M1.5) to learn a recipe
  - Discovery: immediate acquisition from finding a schematic item in the world
- Recipe slot limits by skill tier (Untrained: 0, Trained: limited, Expert: expanded, Master: full)
- DB migration: `recipes` table (full recipe schema), `recipe_slots` table (`character_id` → recipe IDs by tier), `player_known_recipes` table, `materials_catalog` table
- Content: `content/recipes.json` with 70+ entries across all categories and tiers
- Agent tool: `learn_recipe(character_id, recipe_id, acquisition_method)` → adds recipe to known list, validates slot capacity
- Agent tool: `query_recipe_requirements(recipe_id)` → returns materials, workspace, DC, and time requirements
- Pure function: `validate_recipe_slot_capacity(character_skills, known_recipes, new_recipe)` → bool
- Pure function: `check_material_requirements(inventory, recipe)` → met/unmet materials list with substitution options

**Acceptance criteria:**
- [ ] Recipe schema includes all fields: id, name, category, tier, materials, workspace, DC, time, cycles, output, study_cost, discovery_sources, narration_cues
- [ ] Material requirements support quantity, tier minimum, and substitutable flag
- [ ] Recipe Slots acquisition respects tier-limited capacity based on skill tier
- [ ] Training acquisition requires correct number of async cycles (1-6) to complete
- [ ] Discovery acquisition grants recipe immediately upon schematic find
- [ ] `validate_recipe_slot_capacity` correctly enforces limits per skill tier
- [ ] `check_material_requirements` identifies met/unmet materials and suggests valid substitutions
- [ ] DB migrations create all four tables with correct schemas
- [ ] `content/recipes.json` contains 70+ recipes across categories
- [ ] Tests cover all three acquisition tracks, slot limits at every skill tier, and material substitution logic

**Key references:**
- *Game Mechanics Crafting — Recipe Schema*
- *Game Mechanics Crafting — Recipe Acquisition Tracks*
- *Game Mechanics Crafting — Material Requirements & Substitution*

### Audit Status (Sprint-004)

<!-- see audit/phase-5-recipes-resolution.md -->

**Status: DEFERRED / NOT_STARTED.** Full M5.1 pipeline (recipe slots, three-track acquisition, materials catalog) is unshipped. What exists: a 4-recipe TS-source-of-truth map in `apps/server/src/activity_templates.ts:94-130` (`iron_sword`, `healing_poultice`, `ward_stone`, `reinforced_shield`) with a minimal `CraftingRecipe` interface missing 11 of 13 spec fields; bare item-id string-arrays for materials; zero crafting-related DB migrations; no `content/recipes.json` (4 of 70+ target entries ≈ 5%); 1 of ~40 spec material types present in `content/items.json`.

| Section | BUILT | DESIGNED | NOT_SHIPPED |
| --- | --- | --- | --- |
| M5.1 — Recipe & Material System (10) | 0 | 2 | 8 |

**Material gaps:**
- `content/recipes.json` does not exist; 4 server-side recipes ≈ 5% of 70+ target.
- `content/materials_catalog.json` (or migration-seeded table) does not exist; 1 of ~40 spec material types present in `content/items.json`.
- `recipe_slots`, `player_known_recipes`, `materials_catalog` tables — none of 17 migrations create them.
- No schematic item type (`type: "schematic"` count = 0); Discovery acquisition track cannot fire.

**Cross-doc deps:**
- M5.1 → Phase 1 M1.2 (skill tiers): slot capacity and tier gating read player Crafting tier (registered at `apps/agent/rules_engine.py:102`).
- M5.1 → Phase 1 M1.5 (async training): the Training acquisition track consumes async cycles via `content/training_activity_types.json:recipe_study`; per-tier cycle-cost mapping is the M5.1 adapter.
- M5.1 → M5.4 catalog: recipes name material ids that must resolve against the items catalog.

**Spec/milestone conflict to record:** Untrained recipe slots — milestone bullet says "Untrained: 0"; spec at `game_mechanics_crafting.md:158` says "Untrained 3". Tracked in `audit/README.md` Sprint-spec-cleanup.

See `audit/phase-5-recipes-resolution.md` for the full coverage matrix.

---

### Milestone 5.2 — Workspace & Crafting Resolution

**Goal:** Implement the four workspace types with access methods and the three-check crafting resolution pipeline that validates recipe knowledge, skill tier, and workspace before rolling.

**Inputs:** M5.1 (recipes and materials), Phase 1 M1.2 (skill tiers for validation), existing NPC disposition system.

**Deliverables:**
- 4 workspace types: Field (always available, limited recipes), Workshop, Forge, Laboratory
- 4 access methods:
  - Field: free, available anywhere, supports only basic recipes
  - NPC rental: Workshop 2sp/day, Forge 5sp/day, Laboratory 10sp/day, Combined 12sp/day
  - Reputation standing: Trusted disposition with settlement grants free access
  - Artificer Portable Lab: class feature, counts as Workshop + basic Laboratory
- **Deferred from Phase 1 (ADR 0005):** the async-activity Artificer training-slot exception. When the Portable Lab item/recipe lands here, also (a) fix `apps/server/src/activities.ts:countActiveBySlot` so a crafting-on-training-slot consumes the training slot (debt `95de7fa141df`), and (b) wire the crafting create path to load player class + portable-lab ownership and pass `archetype`/`hasPortableLab` to `validateSlotAvailability`. The validator seam + its unit tests already exist (`apps/server/src/slot_validation.ts`).
- NPC disposition modifiers on rental price (friendly = discount, hostile = surcharge or refusal)
- Three-check resolution pipeline:
  1. Recipe Knowledge check: does the character know this recipe?
  2. Skill Tier check: is the character's crafting skill tier sufficient for the recipe tier?
  3. Workspace check: does the current workspace support this recipe's requirements?
- Crafting roll: `d20 + skill modifier` vs `crafting_dc` (only if all three checks pass)
- DB migration: `workspace_rentals` table (`character_id`, `workspace_type`, `location_id`, `rental_start`, `rental_end`, `daily_cost`)
- Pure function: `validate_recipe_knowledge(character_id, recipe_id, known_recipes)` → bool
- Pure function: `validate_workspace_tier(workspace_type, recipe)` → bool
- Pure function: `resolve_crafting_check(skill_modifier, crafting_dc)` → result packet with margin
- Agent tool: `query_available_workspaces(character_id, location_id)` → list of accessible workspaces with costs
- Agent tool: `start_crafting_project(character_id, recipe_id, workspace_id)` → runs three-check pipeline, rolls if valid

**Acceptance criteria:**
- [ ] All 4 workspace types defined with supported recipe categories
- [ ] Field workspace is always available but restricted to basic recipes
- [ ] NPC rental costs match spec: Workshop 2sp, Forge 5sp, Lab 10sp, Combined 12sp per day
- [ ] Disposition modifiers correctly adjust rental prices (discount for friendly, surcharge for hostile)
- [ ] Trusted reputation grants free workspace access at that settlement
- [ ] Artificer Portable Lab functions as Workshop + basic Laboratory
- [ ] Artificer async training-slot exception wired + slot accounting consumes the training slot (deferred from M1.6 per ADR 0005; debt `95de7fa141df`)
- [ ] Three-check pipeline gates crafting roll: all three must pass before rolling
- [ ] Crafting roll uses `d20 + skill modifier` vs `crafting_dc`
- [ ] DB migration creates `workspace_rentals` table with correct schema
- [ ] `start_crafting_project` fails gracefully with clear reason when any check fails
- [ ] Tests cover all workspace types, access methods, disposition modifiers, and three-check pipeline

**Key references:**
- *Game Mechanics Crafting — Workspace Types & Access*
- *Game Mechanics Crafting — Three-Check Resolution*
- *Game Mechanics Crafting — NPC Rental Costs*

### Audit Status (Sprint-004)

<!-- see audit/phase-5-recipes-resolution.md -->

**Status: DEFERRED / NOT_STARTED.** No `Workspace` enum, no workspace types, no rental cost table, no three-check gate. `async_rules.resolve_crafting()` at `apps/agent/async_rules.py:34-129` runs the d20 skill roll with no pre-flight checks — server-side validation at `apps/server/src/activities.ts:137-146` is recipe-id existence only. Roll formula `d20 + skill_modifier vs dc` matches spec; `async_rules.resolve_crafting` falls back to `"arcana"` when no skill is named (`async_rules.py:47`, spec calls for `"crafting"`). The 4 shipped recipes use mixed skills (`athletics`, `medicine`, `arcana`); 0 of the 4 use the registered `"crafting"` skill.

| Section | BUILT | DESIGNED | NOT_SHIPPED |
| --- | --- | --- | --- |
| M5.2 — Workspace & Crafting Resolution (11) | 0 | 2 | 9 |

**Material gaps:**
- No `Workspace` enum, `workspace_required` field, or per-tier workspace-vs-recipe gate.
- No `workspace_rentals` migration; cannot track active rentals or daily costs.
- No rental cost table (2sp/5sp/10sp/12sp values absent from code and content).

**Cross-doc deps:**
- M5.2 → existing NPC disposition system: rental gating reads NPC disposition (state exists; rental-price-modifier function is the M5.2 add).
- M5.2 → Phase 6 NPCs / settlement templates: Settlement Workspace Availability matrix requires settlement-size inspection.
- M5.2 → M5.4 (intra-Phase-5): Artificer Portable Lab is itself a Master-tier recipe in the catalog; workspace-type abstraction must exist for the item to grant it.
- M5.2 → M5.3 (intra-Phase-5): quality bands consumed by the resolver; when M5.3 ships, the M5.2 resolver must re-align to spec bands.

**Spec/milestone conflict to record:** Rental disposition modifiers — milestone bullet says "discount for friendly, surcharge for hostile"; spec at `game_mechanics_crafting.md:204-207` gates rental at neutral-or-better (refusal at unfriendly, no surcharge defined). Tracked in `audit/README.md` Sprint-spec-cleanup.

See `audit/phase-5-recipes-resolution.md` for the full coverage matrix.

---

### Milestone 5.3 — Quality Outcomes & Experimentation

**Goal:** Implement the 4-tier quality outcome system and the experimentation mechanic that lets players attempt undocumented recipes at higher difficulty for a chance to discover new recipes.

**Inputs:** M5.2 (crafting resolution for roll results), M5.1 (recipe system for experimentation discovery).

**Deliverables:**
- 4 quality tiers based on crafting roll margin:
  - Exceptional (DC+10 or more): item produced with a random bonus property from per-category table
  - Success (meets DC): standard item as described in recipe
  - Partial (DC-5 to DC-1): functional but flawed item (e.g., weapon with -1 modifier, potion with side effect)
  - Failure (below DC-5): materials consumed, no item produced
- Exceptional bonus properties: per-category tables (weapon bonuses, armor bonuses, potion extras, tool enhancements)
- Partial item flaws: per-category tables (reduced stats, side effects, limited uses, fragility)
- Experimentation mechanic: craft without a known recipe at `DC + 4`; success produces item AND learns recipe, failure consumes materials only
- Pure function: `apply_quality_outcome(roll_margin, recipe, category_tables)` → item with quality modifications
- Pure function: `resolve_experimentation(skill_modifier, base_dc, materials, category_tables)` → item + recipe learned OR materials consumed
- Agent tool: `experiment_with_materials(character_id, materials, intended_output)` → experimentation result

**Acceptance criteria:**
- [ ] Exceptional quality triggers at DC+10 and adds a random bonus property from the correct category table
- [ ] Success quality produces standard item matching recipe output
- [ ] Partial quality (DC-5 to DC-1) produces flawed but functional item with appropriate flaw
- [ ] Failure (below DC-5) consumes all materials and produces nothing
- [ ] Experimentation uses `base_dc + 4` as the crafting DC
- [ ] Successful experimentation produces the item AND adds the recipe to known recipes
- [ ] Failed experimentation consumes materials without producing item or recipe
- [ ] Bonus property and flaw tables exist for each item category
- [ ] `apply_quality_outcome` and `resolve_experimentation` are pure functions
- [ ] Tests cover all four quality tiers, experimentation success/failure, and bonus/flaw table lookups

**Key references:**
- *Game Mechanics Crafting — Quality Outcomes*
- *Game Mechanics Crafting — Experimentation*
- *Game Mechanics Crafting — Bonus Properties & Flaws*

### Audit Status (Sprint-004)

<!-- see audit/phase-5-quality.md -->

**Status: DEFERRED / NOT_STARTED.** The 4-tier spec quality model (`Exceptional` at DC+10 / `Success` at DC / `Partial` at DC-5..DC-1 / `Failure` below DC-5) and the Experimentation system are unshipped. `async_rules.resolve_crafting()` at `apps/agent/async_rules.py:34-129` returns a 4-tier outcome (`success` / `partial` / `unexpected` / `failure`) but the band thresholds diverge: code's `success` fires at `margin>=5` OR `d20==20`, lumping spec's Exceptional and Success together; code's `unexpected` has no spec mapping; code returns half the materials on failure (spec: "materials consumed, nothing produced"). No per-category bonus-property or flaw tables. No `apply_quality_outcome`, `resolve_experimentation`, or `experiment_with_materials` symbols. No `known_recipes` table to receive the experimentation "teaches the recipe" mutation.

| Section | BUILT | DESIGNED | NOT_SHIPPED |
| --- | --- | --- | --- |
| M5.3 — Quality Outcomes & Experimentation (10) | 0 | 4 | 6 |

**Material gaps:**
- Per-category bonus-property and flaw tables — do not exist; spec names the shape but the implementer must author the per-category content (weapons/armor/consumables/tools/ammunition/enchantments).
- `known_recipes` / `player_known_recipes` table — does not exist (gated by M5.1).
- No tracked "failed combination" memory; spec says repeat experiments with the same materials should not retry.
- Hidden Crafting skill counter (spec's `+1 on failure` consolation reward) has no destination.

**Cross-doc deps:**
- M5.3 ↔ M5.2 (intra-Phase-5): quality bands consumed by the M5.2 resolver; when M5.3 ships, `async_rules.resolve_crafting` must re-align to spec bands.
- M5.3 → M5.1 (intra-Phase-5): Experimentation's "teaches the recipe" side effect writes to `player_known_recipes` (M5.1 deliverable).
- M5.3 ↔ M5.4 (intra-Phase-5): Master tier's Masterwork declaration triggered here, gated by M5.4 catalog work.
- M5.3 → `game_mechanics_archetypes.md` Artificer: Tool Expertise + safe Hollow-material handling cross-references Phase 2.

**Spec/milestone conflict to record:** `async_rules.resolve_crafting` returns half materials on Failure (`async_rules.py:88-91`); spec at `game_mechanics_crafting.md:106` is explicit "Materials consumed. Nothing produced." Tracked in `audit/README.md` Sprint-spec-cleanup.

See `audit/phase-5-quality.md` for the full coverage matrix.

---

### Milestone 5.4 — Durability & Item Catalog

**Goal:** Implement the durability system with hit-based depletion, Hollow corrosion, and build out the full item catalog covering weapons, armor, consumables, tools, and enchantments.

**Inputs:** M5.3 (quality outcomes for item creation), M5.1 (materials catalog), existing item entities.

**Deliverables:**
- 4 durability tiers: Fragile (low hits), Standard, Reinforced, Masterwork (highest hits)
- Hit depletion system: items lose 1 durability point on use or when taking damage; at 0 = broken
- Hollow corrosion: items in Hollow-influenced areas lose durability at double the normal rate
- Item repair mechanics: repair cost scales with durability tier and damage level
- Full item catalog covering:
  - Weapons: damage dice, properties (finesse, heavy, light, thrown, etc.), weight, price, rarity
  - Armor: AC value, properties (stealth disadvantage, STR requirement), weight, price, rarity
  - Consumables: potions (healing, buffs, utility), poisons (damage, debuff), ammunition (standard, special)
  - Tools: crafting tools, thieves' tools, herbalism kit, etc. with skill associations
  - Enchantments: magical properties applied to base items
- Magic item tiers: Rare (requires tier 3 crafting), Legendary (requires tier 4 crafting)
- DB migration: `items_catalog` table updated with durability fields, full item type coverage
- Content: `content/items.json` expanded with all item types, stats, and crafting-system properties
- Pure function: `apply_durability_damage(item_state, damage_amount, is_hollow_zone)` → updated item state
- Pure function: `check_item_condition(item_state)` → condition label (pristine, worn, damaged, broken)
- Pure function: `calculate_repair_cost(item_state, durability_tier)` → gold cost

**Acceptance criteria:**
- [ ] All 4 durability tiers defined with correct hit point ranges
- [ ] Items lose 1 durability on use/damage and become broken at 0
- [ ] Hollow corrosion applies double durability loss in Hollow-influenced areas
- [ ] Repair cost correctly scales with durability tier and current damage level
- [ ] Item catalog includes weapons with damage, properties, weight, price, and rarity
- [ ] Item catalog includes armor with AC, properties, weight, price, and rarity
- [ ] Item catalog includes consumables (potions, poisons, ammunition) with effects
- [ ] Item catalog includes tools with skill associations
- [ ] Magic items correctly gated by crafting tier (Rare = tier 3, Legendary = tier 4)
- [ ] `content/items.json` expanded with full crafting-system item entries
- [ ] DB migration updates `items_catalog` with durability and expanded type fields
- [ ] All durability functions are pure with no side effects
- [ ] Tests cover all durability tiers, Hollow corrosion, repair costs, and item condition labels

**Key references:**
- *Game Mechanics Crafting — Durability System*
- *Game Mechanics Crafting — Item Catalog*
- *Game Mechanics Crafting — Magic Item Tiers*

### Audit Status (Sprint-004)

<!-- see audit/phase-5-durability.md -->

**Status: DEFERRED / NOT_STARTED.** The durability system (4 tiers, hit-depletion, Hollow double-corrosion, repair pricing) is entirely unshipped. No `Durability` enum, no `apply_durability_damage` / `check_item_condition` / `calculate_repair_cost` functions, no `durability` column on items, no per-item HP tracking. The `Item` interface at `packages/shared/src/entities/item.ts:9-25` carries 13 fields but is **missing** damage_dice, AC, properties, durability, attunement, audio_cue, and magic-item-tier gating. `content/items.json` covers ~34% of the spec catalog by count (29 / 85) and ~0% by structured-field coverage (0 entries with durability / AC / damage_dice / properties array). No `items_catalog` migration.

| Section | BUILT | DESIGNED | NOT_SHIPPED |
| --- | --- | --- | --- |
| M5.4 — Durability & Item Catalog (13) | 0 | 4 | 9 |

**Material gaps:**
- `Item.durability_tier` + `Item.current_hits` — do not exist; backfill across 29 items.json entries required.
- `Item.damage_dice` + `Item.properties` for weapons — do not exist; spec authors 15 weapon entries.
- `Item.ac` + armor properties — do not exist; spec authors 10 armor entries.
- Magic-item content — 6 spec Rare + 4 spec Legendary unique items absent from items.json.
- `audio_cue?: string` field missing — spec magic items carry explicit Audio: lines per audio-first invariant.
- `Item.tier: 1 | 2` is undersized — spec defines 4 rarity tiers; widen to `1 | 2 | 3 | 4`.

**Cross-doc deps:**
- M5.4 → M5.1 (intra-Phase-5): magic items name crafting recipes; recipes (M5.1) and magic items (M5.4) cross-reference by id.
- M5.4 → M5.3 (intra-Phase-5): Masterwork declaration is a Master-tier quality outcome producing a Masterwork-durability-tier item.
- M5.4 → M5.2 (intra-Phase-5): repair pricing routes through NPC blacksmith rental.
- M5.4 → Phase 4 Combat: hit-depletion fires on per-encounter / per-damage-taken / per-shield-reaction events.
- M5.4 → Phase 3 Magic: caster-only attunement (Veil-Sight Lens, Ring of Resonance Dampening) requires attunement + caster-class gating.
- M5.4 → CLAUDE.md audio-first invariant: magic-item audio cues belong at the schema layer.

**Spec/milestone conflicts to record:**
- **Repair-pricing axis** — spec keys cost on item-rarity-tier (Common/Uncommon/Rare/Legendary at `game_mechanics_crafting.md:542-549`); milestone acceptance bullet 4 says "scales with durability tier and current damage level" — different axes (rarity vs durability vs damage-level).
- **Legendary exception** — Thornridge's Stand carries "Cannot be crafted" (quest-only), breaking the milestone's "Magic items gated by crafting tier" gate.

Both tracked in `audit/README.md` Sprint-spec-cleanup.

See `audit/phase-5-durability.md` for the full coverage matrix.
