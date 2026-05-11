# Phase 9: Economy System

> Source doc: `docs/game_mechanics/game_mechanics_economy.md`
>
> **Parallelism note:** Phase 9 can run in parallel with Phases 2-8 since it only depends on Phase 1 (Core Systems) being complete.

Implements the unified currency system, merchant pricing engine, and quest reward calibration to ensure a coherent in-game economy anchored to player effort.

---

### Milestone 9.1 — Currency System & Price Tables

**Goal:** Implement the three-tier currency model with canonical price reference tables anchored to the cost of unskilled labor.

**Inputs:** Phase 0 (documentation updates), Phase 1 M1.1 (core resolution for price lookups).

**Deliverables:**
- Currency model: cp (copper piece) → sp (silver piece) → gc (gold crown), 10:1 ratio at each step
- Economic anchor constant: 1 sp = 1 day's unskilled labor
- Wage scale: Unskilled 1 sp/day, Skilled 1.5 sp/day, Expert 2-3 sp/day
- Canonical price tables for 14 categories: weapons (1-40 sp), armor (3 sp to 100 gc), food, lodging, transport, clothing, tools, spell components, potions, services, workspaces, animals, containers, misc adventuring gear
- Starting gold by archetype: 10 sp (most archetypes), 15 sp (Diplomat)
- DB seed: canonical price reference lookups
- Pure function: `convert_currency(amount, from_denomination, to_denomination)` → converted amount
- Pure function: `lookup_base_price(item_id)` → price in sp

**Acceptance criteria:**
- [ ] Currency conversion is correct across all denominations (100 cp = 10 sp = 1 gc)
- [ ] All 14 price categories populated with at least 3 items each
- [ ] Wage scale constants defined and referenced in price justifications
- [ ] Starting gold returns correct amount per archetype
- [ ] DB seed script populates canonical price reference table
- [ ] `convert_currency` handles all denomination pairs correctly including fractional results
- [ ] Tests verify price table completeness and conversion math

**Key references:**
- *Game Mechanics Economy — Currency System*
- *Game Mechanics Economy — Economic Anchor*
- *Game Mechanics Economy — Canonical Price Tables*

---

### Milestone 9.2 — Merchant Pricing Engine

**Goal:** Build the dynamic pricing engine that adjusts base prices by NPC disposition and faction reputation as a pure function.

**Inputs:** M9.1 (price tables), existing disposition and faction systems.

**Deliverables:**
- Pure function: `calculate_price(base_price, disposition, faction_reputation)` → final price in sp
- Disposition modifiers: Hostile (+20%), Unfriendly (+10%), Neutral (1.0x), Friendly (-10%), Trusted (-20%)
- Faction reputation modifier (stacks with disposition)
- Workspace rental pricing: Workshop 2 sp/day, Forge 5 sp/day, Laboratory 10 sp/day, Combined 12 sp/day
- Workspace disposition discounts: Friendly pays 80%, Trusted pays 60%
- Mentor fee schedule: 15-100 sp depending on renown tier; Kael Thornridge free (quest-gated)
- Agent tool: `get_merchant_price(item_id, merchant_id, character_id)` → price with breakdown

**Acceptance criteria:**
- [ ] `calculate_price` produces correct results for all 5 disposition levels
- [ ] Disposition and faction modifiers stack correctly (multiplicative)
- [ ] Workspace rental returns correct daily rate for all 4 workspace types
- [ ] Workspace disposition discounts apply correctly (Friendly 80%, Trusted 60%)
- [ ] Mentor fees vary by renown tier and Kael Thornridge returns 0 when quest flag is set
- [ ] `calculate_price` is a pure function with no side effects
- [ ] Tests cover every disposition level, workspace type, and edge cases (zero base price, max modifiers)

**Key references:**
- *Game Mechanics Economy — Merchant Pricing Formula*
- *Game Mechanics Economy — Disposition Modifiers*
- *Game Mechanics Economy — Workspace Rental & Mentor Training Fees*

---

### Milestone 9.3 — Quest Reward Calibration

**Goal:** Validate and calibrate quest rewards against the economic anchor so that player wealth progression feels intentional across all tiers.

**Inputs:** M9.1 (price tables for comparison), M9.2 (merchant pricing for spend validation), existing quest data in `content/quests.json`.

**Deliverables:**
- Reward tier definitions: Tier 1 (25-50 sp), Tier 2 (100-250 sp), Tier 3 (300-700 sp)
- Validation script: checks all quests in `content/quests.json` against reward tier ranges
- Wealth simulation: model starting gold → early-game purchases to verify early pressure exists
- Updated `content/quests.json` with calibrated reward values where needed
- Pure function: `validate_quest_reward(quest_tier, reward_amount)` → valid/invalid with reason
- Documentation: reward rationale notes in quest data (what can a player buy with this reward?)

**Acceptance criteria:**
- [ ] All Tier 1 quest rewards fall within 25-50 sp range
- [ ] All Tier 2 quest rewards fall within 100-250 sp range
- [ ] All Tier 3 quest rewards fall within 300-700 sp range
- [ ] Validation script runs against `content/quests.json` with zero violations after calibration
- [ ] Wealth simulation demonstrates that starting gold (10 sp) creates meaningful early-game purchasing decisions
- [ ] `validate_quest_reward` correctly flags out-of-range rewards with specific reason
- [ ] Tests cover boundary values for each tier (min, max, just outside range)

**Key references:**
- *Game Mechanics Economy — Quest Reward Tiers*
- *Game Mechanics Economy — Starting Gold*
- *Game Mechanics Economy — Systems Not Yet Specified (Loot & Drop Tables)*
