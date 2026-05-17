# Phase 5 Audit — Crafting M5.3 (Quality Outcomes & Experimentation)

Sprint-004 / Milestone 4 (story-002). Read-only audit of `docs/milestones/05_crafting.md` §M5.3 against `docs/game_mechanics/game_mechanics_crafting.md` (587 lines, §Quality Outcomes at 99-107 / §Experimentation System at 244-259 / §Crafting Check DC by Recipe Tier at 90-97 for Exceptional thresholds) and shipped code in `apps/agent/`, `apps/server/`, `packages/shared/src/entities/`, `content/`. Status legend (per story-002 AC): **BUILT** = code present and matches spec; **DESIGNED** = spec is well-defined and partial code exists, but the symbol/feature is missing, renamed, or diverges from spec; **NOT_SHIPPED** = no implementation found at all.

## Summary

| Section | BUILT | DESIGNED | NOT_SHIPPED |
| --- | --- | --- | --- |
| M5.3 — Quality Outcomes & Experimentation | 0 | 4 | 6 |

**Headline finding:** The 4-tier spec-canonical quality model (`Exceptional` at DC+10 / `Success` at DC / `Partial` at DC-5..DC-1 / `Failure` below DC-5) and the Experimentation system (craft without recipe at DC+4, success teaches the recipe) are **unshipped**. What exists is the same `async_rules.resolve_crafting()` at `apps/agent/async_rules.py:34-129` audited in `phase-5-recipes-resolution.md` for M5.1/M5.2 — it returns a 4-tier outcome (`success`/`partial`/`unexpected`/`failure`) but the band thresholds diverge from spec: code's `success` fires at `margin>=5` OR `d20==20`, lumping spec's Exceptional and Success together; code's `unexpected` (catch-all) is NEW with no spec mapping; code's `failure` returns half the materials (spec: "materials consumed, nothing produced"). No per-category bonus-property or flaw tables exist (`grep` against `apps/agent/`, `apps/server/`, `content/` for "bonus", "flaw", "exceptional_table" → 0 matches). No `apply_quality_outcome` / `resolve_experimentation` / `experiment_with_materials` symbols exist anywhere. No `known_recipes` table to receive the "successful experimentation teaches the recipe" mutation. `quality_bonus: int` in `CraftingOutcome` at async_rules.py:21 is an integer 0-3, not a randomly-selected bonus property from a category table.

Naming caveats (deliverables only — all are NOT_SHIPPED unless tagged otherwise):
- Spec deliverable `apply_quality_outcome(roll_margin, recipe, category_tables)` pure function — NOT_SHIPPED. `grep -r 'apply_quality_outcome' apps/` → 0 matches.
- Spec deliverable `resolve_experimentation(skill_modifier, base_dc, materials, category_tables)` pure function — NOT_SHIPPED.
- Spec deliverable `experiment_with_materials(character_id, materials, intended_output)` agent tool — NOT_SHIPPED.
- Existing `async_rules.resolve_crafting()` — DESIGNED: it produces a quality-tiered outcome (the spec's intent) but with divergent thresholds AND no bonus-property / flaw table lookup AND no separate Exceptional band. Re-aligning is M5.3 work; the resolver also serves M5.2 (covered there).

## Coverage matrix

Every subsection of `docs/game_mechanics/game_mechanics_crafting.md` relevant to M5.3 is mapped below. Items marked NEW are spec content with no corresponding milestone item.

| Spec section (file:line) | Milestone item | Notes |
| --- | --- | --- |
| Crafting Check DC by Recipe Tier — Exceptional Thresholds (crafting.md:90-97) | M5.3 — Exceptional at DC+10 | Basic 18 / Trained 22 / Expert 26 / Master 30. Acceptance bullet "Exceptional quality triggers at DC+10 and adds a random bonus property from the correct category table". Code uses `margin>=5` not `margin>=10`. |
| Quality Outcomes table (crafting.md:99-107) | M5.3 — 4 quality tiers | Spec 4 tiers: Exceptional / Success / Partial / Failure. Code 4 tiers: success / partial / unexpected / failure. **Naming/threshold divergence to record.** |
| Exceptional bonus properties (crafting.md:103) | M5.3 — per-category bonus-property tables | "+1 to a stat, extra durability, minor enchantment, or cosmetic distinction" — examples not enumerated as a category-keyed table in spec. Acceptance bullet "Bonus property and flaw tables exist for each item category". |
| Partial item flaws (crafting.md:105) | M5.3 — per-category flaw tables | "-1 durability tier, minor cosmetic defect, or situational penalty" — same shape as bonus properties. |
| Failure outcome (crafting.md:106) | M5.3 — Failure consumes materials, no item | Spec is explicit: "Materials consumed. Nothing produced. A lesson learned — gain +1 toward the hidden Crafting skill counter". Code returns half materials on failure (async_rules.py:84-86). **Conflict: also flagged in M5.1+M5.2 audit (Sprint-spec-cleanup item).** The "+1 hidden skill counter" reward is NEW (no acceptance bullet). |
| Experimentation System overview (crafting.md:244-249) | M5.3 — Experimentation mechanic | Acceptance bullets 5-7. Track-2 source #4 (also referenced in M5.1 audit). |
| Experimentation Flow steps 1-3 (crafting.md:250-254) | M5.3 — experimentation at DC+4 | Step 3: "Crafting check at DC +4. Success: item created AND recipe learned permanently. Failure: materials consumed, no recipe learned." Maps to M5.3 acceptance bullets 5/6/7. |
| Experimentation Flow step 4 — no valid recipe path (crafting.md:255) | NEW | When NO recipe exists matching the materials, DM narrates failure + tracks the combination so player doesn't repeat. No acceptance bullet covers the recipe-doesn't-exist path. |
| Master "Masterwork declaration" (crafting.md:77-80) | NEW | "Master crafters can declare an item Masterwork — unique named item." Not in M5.3 acceptance bullets. Cross-doc dep with M5.4 (which gates Masterwork by crafting tier). |
| Artificer experimentation advantage (crafting.md:259) | NEW | Artificer Tool Expertise (double proficiency) + safe Hollow-material handling at Expert tier. Cross-doc dep with `game_mechanics_archetypes.md` Artificer class. Not in M5.3 milestone. |
| Tainted-material Expert gate (crafting.md:60-62 Resolution Flow Check 5) | NEW (M5.2/M5.3 boundary) | `if any_tainted(materials) and character.crafting_tier < EXPERT: return FAILURE`. Pre-flight gate consumed by quality resolution; lives in M5.2 (gate) and M5.3 (where Expert-tier Artificer override would apply). Not in either milestone's acceptance bullets. |

## M5.3 — Quality Outcomes & Experimentation

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| Exceptional quality triggers at DC+10 and adds a random bonus property from the correct category table | No `Exceptional` outcome band. `async_rules.resolve_crafting` at `apps/agent/async_rules.py:63-75` collapses spec-Exceptional and spec-Success into one `"success"` tier triggered at `margin >= 5` OR `d20 == 20`. `quality_bonus = min(margin, 3)` at async_rules.py:65 is an integer 0-3, not a property selection from a category table. No category table exists (`grep -rn 'bonus_property\|exceptional_table\|category_table' apps/ content/` → 0 matches). | `apps/agent/tests/test_async_rules.py:44-117` exercises `resolve_crafting` outcome bands by RNG seed — tests the code's `success`/`partial`/`failure` strings, NOT the spec's Exceptional/Success/Partial/Failure (`grep -in 'Exceptional' apps/agent/tests/` → 0 matches). | NOT_SHIPPED |
| Success quality produces standard item matching recipe output | `async_rules.resolve_crafting` returns `crafted_item_id=result_item_id, crafted_item_name=result_item_name` for the `"success"` tier (async_rules.py:67-69). The "success" tier is overloaded (covers spec-Exceptional+Success) but produces an item. | `test_async_rules.py:64,78,90` cover the success tier. | DESIGNED (output produced; tier-band conflation with Exceptional means "standard item" isn't isolated from "bonus item") |
| Partial quality (DC-5 to DC-1) produces flawed but functional item with appropriate flaw | `async_rules.resolve_crafting:78-89` returns a "partial" tier for `margin >= 0` (below the success threshold of margin>=5). Item IS produced (`crafted_item_id = result_item_id`). **No flaw application** — no `flaw_property` field set, no category-keyed flaw table consulted. `decision_options` offer "keep" or "rework" — flavor only, no mechanical flaw. Threshold range diverges: spec says DC-5..DC-1 (margin -5..-1); code says margin 0..4 (positive-but-below-success). | `test_async_rules.py` covers the "partial" tier string. | DESIGNED (tier exists with item produced; flaw application + correct margin range NOT_SHIPPED) |
| Failure (below DC-5) consumes all materials and produces nothing | `async_rules.resolve_crafting:90-101` returns "failure" for `d20 == 1` OR `margin < -5`. **Returns half the materials** (async_rules.py:84-86: `materials_consumed = required_materials[:half]; materials_returned = required_materials[half:]`). Spec at crafting.md:106 is explicit: "Materials consumed. Nothing produced." `crafted_item_id = None, crafted_item_name = None` — the "nothing produced" half matches. **Conflict on materials-consumed-vs-returned.** Threshold matches spec (margin<-5). | `test_async_rules.py` covers the "failure" tier string. | DESIGNED (band threshold + nothing-produced correct; half-materials-return diverges from spec) |
| Experimentation uses `base_dc + 4` as the crafting DC | No `resolve_experimentation` symbol. `grep -rn 'resolve_experimentation\|experiment_with_materials\|base_dc.*4\|DC.*\+.*4' apps/agent apps/server packages/shared` → 0 matches. The `+4` modifier is referenced ONLY in spec text. | None | NOT_SHIPPED |
| Successful experimentation produces the item AND adds the recipe to known recipes | No experimentation symbol. No `known_recipes` table or `player_known_recipes` table (already audited in phase-5-recipes-resolution.md M5.1 §"DB migrations create all four tables" — 0 of 4 tables exist). The "teach the recipe" side effect has no destination. | None | NOT_SHIPPED |
| Failed experimentation consumes materials without producing item or recipe | No experimentation symbol. The "failure consumes materials" rule would route through the same resolve_crafting failure tier (which currently returns half) — but no experimentation path invokes it. | None | NOT_SHIPPED |
| Bonus property and flaw tables exist for each item category | No table files in `content/` (`ls content/` lists 16 files; none named `bonus_properties`, `quality_flaws`, `crafting_modifiers`, or category-keyed equivalents). No Python data structure (`grep -rn 'BONUS_PROPERTIES\|FLAW_TABLE\|QUALITY_MODIFIERS' apps/agent` → 0 matches). The spec at crafting.md:103-105 names the SHAPE of these tables (per-category, with examples) but does not itself enumerate them — implementer needs to draft them as content. | None | NOT_SHIPPED |
| `apply_quality_outcome` and `resolve_experimentation` are pure functions | Neither symbol exists. `async_rules.resolve_crafting` is *almost* the spec's `apply_quality_outcome` collapsed with the DC roll — but it's a coupled function (does the d20 roll AND the band selection AND outcome construction), not the spec's clean factoring (roll separately, apply outcome separately). | None | NOT_SHIPPED |
| Tests cover all four quality tiers, experimentation success/failure, and bonus/flaw table lookups | `apps/agent/tests/test_async_rules.py:44-117` covers `resolve_crafting` for its 4 tiers (success/partial/unexpected/failure) and RNG determinism. **No tests** for spec's Exceptional band, experimentation, or bonus/flaw table lookups (none of those exist). | `test_async_rules.py` resolve_crafting coverage exists for code's bands; spec's bands have 0 coverage. | DESIGNED (existing tier-coverage tests need rewriting to spec bands once resolve_crafting is re-aligned; experimentation + bonus/flaw NOT_SHIPPED) |

**Deliverables status:**
- 4 quality tiers (Exceptional / Success / Partial / Failure): DESIGNED (4 tiers exist but with divergent names + thresholds; Exceptional-as-separate-band NOT_SHIPPED).
- Exceptional bonus properties per-category tables: NOT_SHIPPED.
- Partial item flaws per-category tables: NOT_SHIPPED.
- Experimentation mechanic (DC+4, success teaches recipe): NOT_SHIPPED.
- Pure function `apply_quality_outcome(roll_margin, recipe, category_tables)`: NOT_SHIPPED.
- Pure function `resolve_experimentation(skill_modifier, base_dc, materials, category_tables)`: NOT_SHIPPED.
- Agent tool `experiment_with_materials(character_id, materials, intended_output)`: NOT_SHIPPED.

## Material gaps

Content / data gaps that block M5.3 from leaving DESIGNED state:

1. **Per-category bonus-property tables** — do not exist. Spec at crafting.md:103 names the shape ("+1 to a stat, extra durability, minor enchantment, or cosmetic distinction") but the implementer must author the per-category tables (weapons, armor, consumables, tools, ammunition, enchantments). The 4 categories of shipped recipes (iron_sword=weapon, healing_poultice=consumable, ward_stone=enchantment, reinforced_shield=armor) all need bonus-property tables; the spec catalog at crafting.md:263-340 implies 6 categories total.
2. **Per-category flaw tables** — same shape as bonus properties, same gap. Spec at crafting.md:105 names the shape (-1 durability tier, cosmetic defect, situational penalty). Implementer-authored.
3. **`known_recipes` / `player_known_recipes` table** — does not exist (already a M5.1 gap). The experimentation success path's "teaches the recipe permanently" side effect has no persistence destination.
4. **Tracked "combination doesn't work" memory** — spec at crafting.md:255 says repeat experiments with the same failed materials should not retry. No `player_failed_experiments` table or in-memory equivalent.
5. **Hidden Crafting skill counter** — spec at crafting.md:106 says failure grants "+1 toward the hidden Crafting skill counter" as a consolation reward. No counter exists (no `crafting_failures` column on player, no skill-advancement-on-failure hook in `apps/agent/skill_persistence.py`).

## Cross-doc deps

- **M5.3 ↔ M5.2 (intra-Phase-5).** The quality bands are computed from the crafting roll margin produced by M5.2's resolver. `async_rules.resolve_crafting` already encodes a divergent version; when M5.3 ships, the M5.2 resolver must be re-aligned to spec bands (this exact cross-link is also recorded in `phase-5-recipes-resolution.md` Cross-doc deps).
- **M5.3 → M5.1 (intra-Phase-5).** Experimentation's "teaches the recipe permanently" side effect writes to the `player_known_recipes` table (M5.1 deliverable). Without M5.1's persistence layer, M5.3 experimentation cannot complete.
- **M5.3 ↔ M5.4 (intra-Phase-5).** Master tier's Masterwork declaration (crafting.md:77-80) is gated by M5.4 catalog work (Masterwork items are tracked in the item catalog) but triggered from M5.3 quality outcome (Master + result >= Success). Workspace-type abstraction and catalog must both exist for the Masterwork path to fire.
- **M5.3 → `game_mechanics_archetypes.md` Artificer.** Artificer Tool Expertise (double proficiency on Crafting checks) and Hollow-safe Expert tier (crafting.md:259) require archetype-feature plumbing. Cross-doc dep with Phase 2 audit (`phase-2-archetypes.md`) — Artificer is one of the Phase 2 archetypes.
- **M5.3 → `game_mechanics_decisions.md`.** Decisions 36-43 cover crafting per the spec footer at crafting.md:587. Worth a forward-reference when those decisions land in execution_plan.json.

## Out-of-scope findings (Sprint-spec-cleanup punch list)

- Half-materials-on-failure spec/code conflict — already filed by story-001 in `phase-5-recipes-resolution.md` Sprint-spec-cleanup; capstone records once.
- `async_rules.resolve_crafting` `tier` field uses strings `"success"`/`"partial"`/`"unexpected"`/`"failure"`. Spec uses `Exceptional`/`Success`/`Partial`/`Failure`. The `"unexpected"` band has no spec mapping (catch-all fallback for `d20 != 1 && margin < 0 && margin >= -5`). When M5.3 ships, the band-naming convention should align to spec — naming is part of the API surface for downstream tools/UI.
- `quality_bonus: int` in `CraftingOutcome` (async_rules.py:21) is an integer 0-3 derived from `min(margin, 3)`. Spec's Exceptional gives a bonus PROPERTY (variant from a category table), not a numeric bonus. When M5.3 ships, this field will need replacement with a structured bonus-property payload (or removal in favor of a separate `bonus_property: BonusProperty | None` field).
- Hidden Crafting skill counter (crafting.md:106) — failure grants +1 toward hidden skill counter. Worth recording as a missing-data-shape note for whoever ships M5.3 + skill persistence.
