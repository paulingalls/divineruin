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
- [x] Recipe schema includes all fields: id, name, category, tier, materials, workspace, DC, time, cycles, output, study_cost, discovery_sources, narration_cues
- [x] Material requirements support quantity, tier minimum, and substitutable flag
- [x] Recipe Slots acquisition respects tier-limited capacity based on skill tier
- [x] Training acquisition requires correct number of async cycles (1-6) to complete
- [x] Discovery acquisition grants recipe immediately (learn_recipe `learned_via=discovery`); the in-world schematic-item find that triggers it is M5.4 content
- [x] `validate_recipe_slot_capacity` correctly enforces limits per skill tier
- [x] `check_material_requirements` identifies met/unmet materials and suggests valid substitutions
- [x] DB migrations create all four tables with correct schemas
- [x] `content/recipes.json` contains 70+ recipes across categories
- [x] Tests cover all three acquisition tracks, slot limits at every skill tier, and material substitution logic

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
- M5.1 → Phase 1 M1.5 (async training): the Training acquisition track consumes async cycles via the `recipe_study` training activity type. (The per-tier `tier_cycles` cost-mapping adapter — `get_recipe_study_cycles`/`parse_recipe_study_cycles` — was forward-laid but never wired to a production learn path; it and its `tier_cycles` content map were deleted at sprint-013 close per the delete-if-unwired gate. Re-derive the cost mapping when the recipe_study-learn path is actually built.)
- M5.1 → M5.4 catalog: recipes name material ids that must resolve against the items catalog.

**Spec/milestone conflict to record:** Untrained recipe slots — milestone bullet says "Untrained: 0"; spec at `game_mechanics_crafting.md:158` says "Untrained 3". Tracked in `audit/README.md` Sprint-spec-cleanup.

See `audit/phase-5-recipes-resolution.md` for the full coverage matrix.

### CAPSTONE — M5.1 shipped (sprint-012, story-007)

<!-- capstone-footer: grep "CAPSTONE — M5.1" -->

**Status: SHIPPED.** All 10 M5.1 acceptance criteria above are met end-to-end.

- **Story chain:** story-001 (migration 019 + shared Recipe/MaterialReq types) → 002 (73 recipes + 49 materials JSON + content guard) → 003 (TS DB loader) → 004 (killed hardcoded CRAFTING_RECIPES const) → 005 (Python accessors) → 006 (recipe_validation + learn_recipe/query_recipe_requirements tools) → 008 (player_known_recipes CASCADE FK, migration 020) → **007 (this capstone)**.
- **Capstone proof:** `apps/agent/tests/acceptance/test_story_007_capstone.py` proves the DB-loaded recipe flow composes across both surfaces against one seeded testcontainer — message_event (Python `learn_recipe` + `query_recipe_requirements`) and http_websocket (a spawned Bun `src/index.ts` serving `GET /api/activity-templates` + `POST /api/activities` crafting). Cross-language seam assertion: the recipe parsed straight from the testcontainer `recipes` row (cache-bypassed, so the seam can't false-green off a sibling test's Redis entry) is identical (name, dc, materials, output) to what the TS REST surface exposes for the same id. 4/4 capstone tests green via `bun run test:acceptance`.
- **Also landed in story-007:** slot caps loaded from the `recipe_slots` DB table (no hardcoded Python copy — concern `d125d022f084`); `narration_cues` typed to canonical `QualityBand`s with fail-loud loaders in both languages (concern `31c6bd30ca97`, constraint `crafting-narration-bands`).
- **Verified-at:** M1 `b6ef618` (slot DB-load), M2 `bb71ccc` (narration bands); capstone commit + final close SHA recorded at sprint-close.

**Open follow-ups:**
- **Try-2 dated gate (RESOLVED at sprint-013 close):** `check_material_requirements` (`recipe_validation.py`) **was wired** — it is now the pre-flight pipeline's Check 4 (`preflight_pipeline.py:65`), so it stays. `get_recipe_study_cycles` (`training_rules.py`) was **not** wired to any recipe_study-learn path and was **deleted** (with `set_/parse_recipe_study_cycles`, the `_recipe_study_cycles` map, and the `tier_cycles` content field) per the delete-if-unwired gate. Closes concerns `06364bdcb14b`, `47dd7b5d1320`; debt `55d8dcd38fc0`.
- `check_material_requirements` is greedy per-requirement; M5.2 craft-consume owns the real allocate-then-deduct pass (debt `cdce6c6a776d`).
- Systemic player CASCADE-FK backfill for the other post-008 per-player tables (debt `ac2ad5230209`).

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
- [x] All 4 workspace types defined with supported recipe categories
- [x] Field workspace is always available but restricted to basic recipes
- [x] NPC rental costs match spec: Workshop 2sp, Forge 5sp, Lab 10sp, Combined 12sp per day
- [x] Disposition modifiers correctly adjust rental prices (shipped spec-aligned: Friendly 0.8x / Trusted 0.6x discount, refusal below Neutral; no hostile surcharge per spec — the milestone's "surcharge" wording is the tracked spec-cleanup conflict)
- [ ] Trusted reputation grants free workspace access at that settlement — **DEFERRED to Phase 6** (settlement-availability matrix + NPC-vendor validation; concerns `c5c5871115dc`, `bec87679b223`)
- [x] Artificer Portable Lab functions as Workshop + basic Laboratory
- [x] Artificer async training-slot exception wired + slot accounting consumes the training slot (deferred from M1.6 per ADR 0005; debt `95de7fa141df`)
- [x] Three-check pipeline gates crafting roll: all three must pass before rolling (shipped as a five-check pre-flight pipeline — Knowledge/Tier/Workspace/Materials/Tainted-Expert)
- [x] Crafting roll uses `d20 + skill modifier` vs `crafting_dc` (roll deferred to resolution — `resolve_crafting`, story-005)
- [x] DB migration creates `workspace_rentals` table with correct schema (migration 022)
- [x] `start_crafting_project` fails gracefully with clear reason when any check fails
- [x] Tests cover all workspace types, access methods, disposition modifiers, and three-check pipeline

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

### CAPSTONE — M5.2 shipped (sprint-013, story-007)

<!-- capstone-footer: grep "CAPSTONE — M5.2" -->

**Status: SHIPPED.** 10 of 11 M5.2 acceptance criteria are met end-to-end; the one open criterion (Trusted-reputation free workspace access) is deferred to Phase 6 with the settlement-availability matrix.

- **Story chain:** story-001 (Python workspace substrate — `WorkspaceType` + ordering, `compute_rental_price` disposition pricing, settlement-availability matrix) → 002 (migration 022 `workspace_rentals` + TS `accessibleWorkspaceTier`; consolidated the workspace vocab to one SSOT per language) → 003 (five-check pre-flight pipeline — Knowledge/Tier/Workspace/Materials/Tainted-Expert, pure, first-fail ordering; `preflight_pipeline.py`) → 004 (`materials.py` catalog accessor, read+write DB producers, `allocate_materials` disjoint allocate-then-deduct, and the agent tools `query_available_workspaces` / `rent_workspace` / `start_crafting_project`) → 005 (`resolve_crafting` honors workspace access + tainted-Expert gate at resolution; migration 023 backfills in-flight rows) → 006 (REST workspace gate before material consume + Artificer Portable-Lab training-slot exception with COALESCE slot accounting, debt `95de7fa141df`) → **007 (this capstone)**.
- **Capstone proof:** `apps/agent/tests/acceptance/test_m52_workspace_resolution_capstone.py` closes the real-DB workspace-lookup lane ADR 0003 deferred (concern `939df378f3b7`): the mocked `apps/server/workspace.test.ts` cannot exercise `accessibleWorkspaceTier`'s `expires_at > NOW()` SQL predicate, so the capstone drives it against a real testcontainer over both surfaces — http_websocket (REST crafting create gate) and message_event (Python `query_available_workspaces`). Expired forge rental → access denied (REST 400 before consume + no row; tool omits forge); same rental active or standing → access granted (REST 200; tool lists forge). Both surfaces are predicate-load-bearing (mutation-verified). 4/4 green via `bun run test:acceptance`.
- **Also landed in story-007 (adopted cleanups):** deleted the dead `recipe_study_cycles` vertical (delete-if-unwired gate); split `activities.ts` (582L, over cap) into `activity_create.ts` + `activities.ts` per the new `file-size-touch-split` convention, with a SQL-match-keyed mock harness replacing positional indexing (concern `109567241849`); widened the slot-check FOR-UPDATE lock to `in_progress`+`resolving` to match `countActiveBySlot` (debt `d80282969804`); routed `resolve_attack` through the `_roll_d20_check` primitive (debt `a51be5428cc4`).
- **Verified-at:** capstone proof `22580b0`; final close SHA recorded at sprint-close.

**Open follow-ups:**
- **M5.4 cross-language Artificer convergence:** the Portable-Lab slot exception is wired on the TS REST path only; the Python agent path (`crafting_tools.py` slot cap + `count_active_by_slot`, which reads `activity_type` not `data.slot`) is still unaware — a lab Artificer gets asymmetric REST-vs-voice gates until M5.4 makes the Portable Lab obtainable (risk `b335bb95acbd`; concerns `0c38eb0f5b2c`, `7fa70fc60c03`).
- **Phase 6:** Trusted-reputation free access + settlement-availability matrix + `rent_workspace` NPC-vendor/co-location validation (concerns `c5c5871115dc`, `bec87679b223`).
- **Economy milestone:** `rent_workspace` debits gold at interim 10sp=1gp (fractional gold); reconcile when currency sub-units are formalized (concern `67c8f2962302`).
- **M5.3 kickoff:** DM dispatch tools at 17/20 `MAX_STRICT_TOOLS`; the M5.3 crafting surface will breach 20 and force the location+intent sub-agent split (concern `99c31a6db9b3`).

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

**Acceptance criteria:** _(all met — sprint-014; see capstone footer below)_
- [x] Exceptional quality triggers at DC+10 and adds a random bonus property from the correct category table
- [x] Success quality produces standard item matching recipe output
- [x] Partial quality (DC-5 to DC-1) produces flawed but functional item with appropriate flaw
- [x] Failure (below DC-5) consumes all materials and produces nothing
- [x] Experimentation uses `base_dc + 4` as the crafting DC
- [x] Successful experimentation produces the item AND adds the recipe to known recipes
- [x] Failed experimentation consumes materials without producing item or recipe
- [x] Bonus property and flaw tables exist for each item category
- [x] `apply_quality_outcome` and `resolve_experimentation` are pure functions
- [x] Tests cover all four quality tiers, experimentation success/failure, and bonus/flaw table lookups

**Key references:**
- *Game Mechanics Crafting — Quality Outcomes*
- *Game Mechanics Crafting — Experimentation*
- *Game Mechanics Crafting — Bonus Properties & Flaws*

### Audit Status (Sprint-004)

<!-- see audit/phase-5-quality.md -->

**Status: SUPERSEDED — M5.3 shipped in sprint-014; see the capstone footer below.** _(Sprint-004 snapshot retained for history.)_ The 4-tier spec quality model (`Exceptional` at DC+10 / `Success` at DC / `Partial` at DC-5..DC-1 / `Failure` below DC-5) and the Experimentation system are unshipped. `async_rules.resolve_crafting()` at `apps/agent/async_rules.py:34-129` returns a 4-tier outcome (`success` / `partial` / `unexpected` / `failure`) but the band thresholds diverge: code's `success` fires at `margin>=5` OR `d20==20`, lumping spec's Exceptional and Success together; code's `unexpected` has no spec mapping; code returns half the materials on failure (spec: "materials consumed, nothing produced"). No per-category bonus-property or flaw tables. No `apply_quality_outcome`, `resolve_experimentation`, or `experiment_with_materials` symbols. No `known_recipes` table to receive the experimentation "teaches the recipe" mutation.

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

### CAPSTONE — M5.3 shipped (sprint-014, story-005)

<!-- capstone-footer: grep "CAPSTONE — M5.3" -->

**Status: SHIPPED.** All 10 M5.3 acceptance criteria are met end-to-end.

- **Story chain:** story-001 (recorded the 5 binding conflict decisions — spec bands `exceptional/success/partial/failure` as SSOT, all-materials-consumed on Failure, Exceptional at DC+10, hidden skill counter scoped as story-006, `quality_outcomes` DB-loaded Python-only) → 002 (`content/quality_outcomes.json` + migration 024 `quality_outcomes` table + pure band-keyed `apply_quality_outcome`) → 003 (rewrote `resolve_crafting` to the pure-margin 4-band model — Exceptional DC+10 / Success / Partial DC-5..-1 / Failure <DC-5, no nat-1/20 special-casing, all materials consumed on Failure; extracted `crafting_resolution.py` orchestrator joining the resolver to the DB quality tables) → 004 (`experiment_with_materials` immediate tool at DC+4, `resolve_experimentation`, `player_failed_experiments` migration 025 with no-match-only dedup) → 006 (hidden Crafting skill counter, +1 on Failure — migration 026 `player_crafting_skill_counter`, atomic-UPSERT increment, async-worker failure hook; en route, touch-split `async_worker.py`→`async_worker_training.py` and `db_mutations.py`→`db_mutations_divine.py`, resolving file-size debts `f3194b59b4ab` + `1f235ab5066a`) → **005 (this capstone)**.
- **Capstone proof:** `apps/agent/tests/acceptance/test_m53_quality_outcomes_capstone.py` proves M5.3's surfaces compose against one seeded testcontainer. Part A — all four bands resolve through the production `crafting_resolution.resolve_crafting_outcome`, which fetches the recipe category + that category's `quality_outcomes` row from the DB and threads it into the resolver; Exceptional draws a `bonus_property` and Partial a `flaw` that are members of the DB-loaded weapon table (story-002 ⨯ story-003). Part B — a crafting Failure resolves end-to-end through the real async worker (only the LLM/TTS boundary mocked) and the hidden Crafting skill counter reads +1, asserting `gate=="tainted_expert"` so the workspace gate can't mask it (story-003 ⨯ story-006; this fulfills the deferred story-006 AC#4, decision `crafting-counter-ac4-deferred`). Part C — experimentation (story-004, the message_event surface): a no-match consumes materials and records `player_failed_experiments` with no-match-only dedup (row count stays 1 on retry), and a discoverable recipe is learned on success. 4/4 green via `bun run test:acceptance`.
- **Verified-at:** capstone proof `5822526`; final close SHA recorded at sprint-close.

**Open follow-ups:**
- **M5.4 cross-language Artificer convergence:** the Portable-Lab slot exception + slot accounting remain TS-REST-only; the Python agent path is still unaware (risk `b335bb95acbd`).
- **Hidden-counter semantics:** the failure-band increment is at-most-once (a separate await from the outcome-cache write, deliberately — preserves the cached LLM narration on the rare failure-retry path rather than re-running the LLM); revisit if exactly-once is ever required (concern `960a7a9fcb15`).
- **Economy milestone:** `rent_workspace` fractional-gold reconciliation (concern `67c8f2962302`).
- **File-size debt:** `debug.ts` (522L) still owes its SRP split (debt `9c8becfce881`); `db_mutations.py`/`async_worker.py` were split in this milestone.

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
- [x] All 4 durability tiers defined with correct hit point ranges (`durability.DURABILITY_MAX_HITS`: fragile 3 / standard 10 / reinforced 25 / masterwork 50)
- [x] Items lose 1 durability on use/damage and become broken at 0 (`apply_durability_damage` + combat hit emission story-003)
- [x] Hollow corrosion applies double durability loss in Hollow-influenced areas (`is_hollow_zone` 2× in `apply_durability_damage`, driven by `session.corruption_level >= 2`)
- [x] Repair cost correctly scales with **item rarity** (shipped keyed on rarity per the recorded repair-pricing-axis spec-cleanup `docs/game_mechanics/game_mechanics_crafting.md:542-549`; the milestone's "durability tier and damage level" axis was superseded) + disposition multiplier
- [x] Item catalog includes weapons with damage (`damage_dice`), properties, weight, price (`value_base`), and rarity
- [x] Item catalog includes armor with AC, properties, weight, price (`value_base`), and rarity
- [x] Item catalog includes consumables (potions, poisons, ammunition) with `effects`
- [x] Item catalog includes tools (9 entries) — **caveat:** skill is expressed in `effects`/`tags` prose, not a structured `skill` field (minor catalog gap)
- [x] Magic items correctly gated by crafting tier (Rare → Expert recipe-tier, Legendary → Master; `validate_magic_item_craft_tier`, enforced as a content invariant)
- [x] `content/items.json` expanded with full crafting-system item entries (121 items)
- [x] Item catalog ships durability + expanded type fields — **different-means:** via `content/items.json` → the `items` table + loader (DB-loaded content SSOT), not a separate `items_catalog` migration (assumption `14de9e3b95ee`)
- [x] All durability functions are pure with no side effects (`durability.py`)
- [x] Tests cover all durability tiers, Hollow corrosion, repair costs, and item condition labels (unit tests + the capstone E2E below)

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
- **Repair-pricing axis** — spec keys cost on item-rarity-tier (Common/Uncommon/Rare/Legendary at `docs/game_mechanics/game_mechanics_crafting.md:542-549`); milestone acceptance bullet 4 says "scales with durability tier and current damage level" — different axes (rarity vs durability vs damage-level).
- **Legendary exception** — Thornridge's Stand carries "Cannot be crafted" (quest-only), breaking the milestone's "Magic items gated by crafting tier" gate.

Both tracked in `audit/README.md` Sprint-spec-cleanup.

### CAPSTONE — M5.4 shipped (sprint-015, story-005)

<!-- capstone-footer: grep "CAPSTONE — M5.4" -->

**Status: SHIPPED.** All 13 M5.4 acceptance criteria are met end-to-end; three are satisfied by deliberate different-means (repair-cost axis → rarity, item catalog → `items` table, tool skill → effect prose), noted inline above. This closes M5.4 and **Phase 5 (Crafting)**.

- **Story chain:** story-001 (durability pure fns — 4 tiers, `apply_durability_damage` Hollow-2×, `check_item_condition`, `calculate_repair_cost`) → 002 (item-catalog expansion + magic-item craft-tier gate `validate_magic_item_craft_tier`) → 003 (combat durability hit emission, persisted by `_accrue_durability`) → 004 (repair flow: REST quote `GET /api/repair/:itemId` + the `repair_item` agent tool) → 006 (Python↔REST Artificer + pricing convergence) → 008 (item loader / content SSOT) → 009 (BlacksmithAgent + repair handoff) → 010 (9 magic-item recipes + items + attunement resolver) → 011 (repair-pricing SSOT content→DB) → 014 (errand wait-with-retry) → 017 (container-infra reconciliation + parallel gate) → **005 (this capstone)**.
- **Capstone proof:** `apps/agent/tests/acceptance/test_durability_e2e.py` proves the durability surfaces compose across both surfaces against one seeded testcontainer — **message_event** (4-tier accrual + Hollow-2× via `session.corruption_level` persisted through `_accrue_durability`; the `repair_item` blacksmith tool restoring durability to tier-max + debiting gold at the rarity price; the magic craft-tier content invariant over the seeded items↔recipes join) and **http_websocket** (Bun `GET /api/repair/:itemId?npc=` quote — rarity tier load-bearing, `rare > common`, and priced identically to the agent tool, proving one rarity SSOT). 5/5 green via `uv run pytest -m acceptance`.
- **Different-means resolutions:** repair cost keys on **item rarity** (`calculate_repair_cost(rarity)` + disposition multiplier), not durability-tier/damage-level — the spec-cleanup axis decision; the catalog shipped as `content/items.json` → the `items` table + loader (no separate `items_catalog` migration); tools carry `effects` + `tags` (skill in prose, no structured `skill` field).
- **Verified-at:** this capstone commit (`test_durability_e2e.py`, 5/5 acceptance green); final close SHA recorded at sprint-close.

**Open follow-ups:**
- **enchant-apply mechanic** (`46fd2bf9ae4a`): the 10 `enchant_*` product items resolve but nothing consumes them to mutate target gear — candidate follow-up story.
- **Acceptance Redis cache bleed** (`e3309563507c`): `reset_db_pool` doesn't flush the content cache; self-heals on TTL / fresh per-run Redis.
- **Waterskin duplicate display name** (`0f2c219957a6`): two ids share the "Waterskin" name (DM voice ambiguity); record-only.
- **Carried debt/concerns:** `debug.ts` 522L split (`9c8becfce881`); `pricing.ts` dead TS export (`217189d2c1d1`); cross-language material-gate divergence (`2b76f2452f23`); training error-code slugs dropped (`50460413ce12`).
- **Phase-6 / economy:** fractional-gold reconciliation (`67c8f2962302`), settlement-size SSOT drift (`c5c5871115dc`).
- **From story-017:** `cost_model.md` recompute for LiveKit Cloud (`ec4c0814257e`).
- **Magic gate is content-invariant, not runtime-enforced:** `validate_magic_item_craft_tier` is asserted over the seeded items↔recipes content (so off-tier recipes can't be authored) but has no caller in the live craft flow — an off-tier *runtime* craft would not be rejected. Runtime enforcement is deferred (the player-skill-vs-recipe-tier preflight gate already bounds who can craft what).

See `audit/phase-5-durability.md` for the full coverage matrix.
