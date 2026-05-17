# Phase 9: Economy System

> **Source docs:** `docs/game_mechanics/game_mechanics_economy.md` (canonical pricing); 6 subsystem docs under `docs/game_mechanics/economy/` (`faction_reputation_pricing.md`, `merchant_inventory_restock.md`, `supply_demand_engine.md`, `gold_sink_ledger.md`, `inflation_targets_controls.md`, `game_mechanics_p2p_trade.md`); `docs/game_mechanics/game_mechanics_encounter_roles.md` §Loot Modifiers (currency drops + material sell values).
>
> **Parallelism note:** Phase 9 can run in parallel with Phases 2-8 since it only depends on Phase 1 (Core Systems) being complete.

Implements the unified currency system, the pricing engine (disposition × faction × event × context), merchant inventory + restock, supply/demand event-driven price dynamics, gold sinks, inflation analytics, and Phase 2+ supporting infrastructure for player-to-player trade. The economy is anchored to the cost of unskilled labor (1 sp = 1 day) and balances faucet sources (quest rewards, loot, sales) against eight categories of sinks (maintenance, subsistence, combat, progression, crafting, service, lifestyle, endgame).

## Audit Cross-Ref (Sprint-003 + Sprint-006)

**Sprint-003** — `game_mechanics_encounter_roles.md` §Loot Modifiers (Currency Drop Rules + Material Sell Values + Boss bonus loot) falls under Phase 09 ownership. The encounter_roles overlay loot-side audit (`audit/phase-encounter-roles.md`) recommended a new milestone for loot-side economy, deferred at the time to the Phase 09 rewrite. **Now landed as M9.4** below.

**Sprint-006** — full Phase 9 audit walking 7 spec docs against shipped code. 7 audit files in `audit/`: `phase-9-economy.md`, `phase-9-supply-demand.md`, `phase-9-faction-pricing.md`, `phase-9-restock.md`, `phase-9-gold-sink.md`, `phase-9-inflation.md`, `phase-9-p2p-trade.md`. **Headline: Phase 9 is ~91% NOT_SHIPPED across 326 acceptance items (0 BUILT / 28 DESIGNED / 298 NOT_SHIPPED).** Substrate ships at four touchpoints: `Item.value_base` + `value_modifiers` schema + content (~12 typed items); `starting_gold:int` per archetype (diverges from spec — Diplomat=25 vs 15); `Npc.disposition_modifiers` (field-name collides with spec mechanic — code carries event-deltas, spec means price-tier multipliers); `Npc.inventory_pool` field BUILT (0 of 14 NPCs populate it); `inventory_pools` table + 4 content pools + `player_inventory` + `add_to_inventory`/`remove_from_inventory` narrative-only tools + `god_whispers` table + `god_whisper_generator` (patron-id-driven not economic-state-driven); `rest_mechanics.py` BUILT (no lodging-cost gating); `apps/agent/db_mutations.py` asyncpg `conn` plumbing across 22 sites (no atomic trade primitive).

**Capstone decision `m9-rewrite-single-file`:** 09_economy.md remains a single file with 10 numbered milestones (M9.1-M9.10), 3 inherited from the original scope + 7 new subsystem milestones. Rationale: single source of truth, simpler dep graph (M7 README), matches Phase 5/6 organization pattern. Total acceptance items expanded from 21 → ~80.

**Capstone decision `m9-decisions-73-128-consolidated`:** all 6 sprint-006 audit stories surfaced spec docs that claim "Extracted to `game_mechanics_decisions.md` for canonical reference" — but the canonical log terminated at Decision 72. This was a **consolidation gap, not a documentation gap**: decisions 73-128 always existed inlined at the bottom of each source spec doc, just not propagated to the canonical aggregator. Resolved pre-close by commit `884adeb` (extracted decisions 73-128 from source specs into `game_mechanics_decisions.md`, 56 new entries spanning Encounter Roles / Faction Pricing / Merchant Inventory / Supply & Demand / Gold Sinks / Inflation / P2P Trade). Source spec docs continue to carry inlined Design Decisions sections (self-contained reading); canonical log is now the audit anchor.

See `audit/README.md` Sprint-006 section for the per-story headline summary + capstone annotations + Sprint-spec-cleanup additions.

---

## Milestone Coverage Summary

| Milestone | Scope | BUILT | DESIGNED | NOT_SHIPPED | Audit File |
| --- | --- | --- | --- | --- | --- |
| M9.1 — Currency & Price Tables | gm_economy §Currency / Anchor / Price Tables / Starting Gold | 0 | 3 | 7 | phase-9-economy.md |
| M9.2 — Merchant Pricing Engine | gm_economy §Merchant Pricing Formula + NPC Services + Workspace + Commissions + Mentor Fees | 0 | 2 | 5 | phase-9-economy.md |
| M9.3 — Quest Reward Calibration | gm_economy §Quest Reward Tiers | 0 | 1 | 0 | phase-9-economy.md |
| M9.4 — Loot-side Economy (NEW) | gm_economy §Hollow Material Values + §Currency Drops + encounter_roles loot modifiers | 0 | 0 | 2 | phase-9-economy.md + phase-encounter-roles.md |
| M9.5 — Faction Reputation Pricing (NEW) | economy/faction_reputation_pricing.md | 0 | 3 | 31 | phase-9-faction-pricing.md |
| M9.6 — Merchant Inventory & Restock (NEW) | economy/merchant_inventory_restock.md | 0 | 6 | 56 | phase-9-restock.md |
| M9.7 — Supply & Demand Engine (NEW) | economy/supply_demand_engine.md | 0 | 4 | 39 | phase-9-supply-demand.md |
| M9.8 — Gold Sink Ledger (NEW) | economy/gold_sink_ledger.md | 0 | 3 | 57 | phase-9-gold-sink.md |
| M9.9 — Inflation Targets & Controls (NEW) | economy/inflation_targets_controls.md | 0 | 3 | 60 | phase-9-inflation.md |
| M9.10 — P2P Trade Infrastructure (NEW [Phase 2+]) | economy/game_mechanics_p2p_trade.md (Phase 1 supporting infrastructure only) | 0 | 3 | 41 | phase-9-p2p-trade.md |
| **Total** | | **0** | **28** | **298** | |

**Note on tallies:** counts reflect acceptance items in each audit's Summary table at sprint-006 verification SHAs. They mix code-shippable items, content-authoring items, and design-decision encodings. See audit files for per-section breakdowns.

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

### Audit Status (Sprint-006) — M9.1

<!-- see audit/phase-9-economy.md §Currency System, §Economic Anchor, §Canonical Price Tables, §Starting Gold -->

**Status: DESIGNED↔aspirational** (4 DESIGNED / 8 NOT_SHIPPED).

What ships: `Item.value_base: number` + `value_modifiers?: Record<string, number>` (`packages/shared/src/entities/item.ts:20-21`) — schema BUILT; ~12 weapons + armor in `content/items.json` carry values that **diverge from spec sp by 12-50×** with no consistent denomination scaling (shortsword_basic=100 vs spec 5sp, longsword_guild=200 vs spec 10sp, etc.). `ArchetypeDefinition.starting_gold: int` (`apps/agent/creation_classes.py:21`) ships 18 entries with values 10/15/20/25; spec spread is 2 values (10/15); **Diplomat=25 diverges by +10 sp**.

What does NOT ship: no `Currency` / `Denomination` enum (single untyped int gold); no `convert_currency` / `lookup_base_price` helpers; no economy anchor constant; no DB migration creates a `canonical_prices` table; food/lodging/adventuring gear/spell components content all NOT_SHIPPED.

Honesty note: spec also drifts internally — Spell Components has only 2 items vs M9.1 "14 categories with ≥3 items each" requirement.

---

### Milestone 9.2 — Merchant Pricing Engine

**Goal:** Build the dynamic pricing engine that adjusts base prices by NPC disposition and faction reputation as a pure function.

**Inputs:** M9.1 (price tables), M9.5 (faction reputation pricing — provides the faction modifier table), M9.7 (supply/demand engine — provides the event modifier hook + 0.5×–3.0× clamp).

**Deliverables:**
- Pure function: `calculate_price(base_price, disposition, faction_reputation, region, item)` → final price in sp
- Disposition modifier table (5 tiers: Hostile +20% / Unfriendly +10% / Neutral 1.0× / Friendly -10% / Trusted -20%)
- Multiplicative stacking with faction modifier + event modifier + context modifier; clamp to [0.5×, 3.0×] of base
- Workspace rental pricing (4 workspaces × disposition discount tiers — moved here from gm_economy)
- Mentor training fee schedule (5 bands per gm_economy spec)
- NPC services pricing (11 spec-named services: Heal Wounds 5 sp → Resurrection 1,000+ sp)
- Crafting commission pricing (3 tiers × 2 sourcing modes + 4 repair tiers)
- Agent tool: `get_merchant_price(item_id, merchant_id, character_id)` → price with breakdown
- (Hollow material values are owned by M9.4 Loot-side Economy — referenced here but not duplicated as a deliverable)

**Acceptance criteria:**
- [ ] `calculate_price` produces correct results for all 5 disposition levels combined with all 6 faction levels (5×6 = 30 cells per spec faction-pricing.md L32-38)
- [ ] Multiplicative stacking matches spec (`base × disposition × faction × event × context`, then clamped to [0.5×, 3.0×])
- [ ] Workspace rental pricing matches the 4-row spec table with disposition discount tiers (Friendly 80%, Trusted 60%)
- [ ] NPC services pricing matches the 11-row spec table (Hollow material values moved to M9.4)
- [ ] `calculate_price` is a pure function with no side effects
- [ ] Tests cover every disposition × faction combination, all 4 workspaces, all 11 services, all 3 commission tiers, all 4 repair tiers, clamp lower/upper bounds, and zero-base edge case

**Key references:**
- *Game Mechanics Economy — Merchant Pricing Formula*
- *Game Mechanics Economy — Disposition Modifiers*
- *Game Mechanics Economy — NPC Services / Workspace Rental / Crafting Commissions / Mentor Training Fees*
- *(Hollow Material Values — see M9.4 Loot-side Economy below)*

### Audit Status (Sprint-006) — M9.2

<!-- see audit/phase-9-economy.md §Merchant Pricing Formula, §NPC Services, §Workspace Rental, §Crafting Commissions, §Mentor Training Fees -->

**Status: NOT_SHIPPED** with two DESIGNED findings (Mentor Training Fees + Field-name collision on Npc.disposition_modifiers).

Field-name collision: `Npc.disposition_modifiers?: Record<string, number>` (`npc.ts:33`) ships on the schema and is populated on 14 NPCs in `content/npcs.json` — but the field carries **per-action disposition deltas** (e.g. `defended_millhaven: 5`, `lied_about_findings: -4`), not the spec's 5-tier disposition price-modifier table. Schema reuse opportunity but **rename or add a separate `price_disposition_modifiers` field** required before M9.2 can ship.

What does NOT ship: no `calculate_price` / `apply_pricing_modifiers` / `clamp_price` function; zero of 11 NPC service handlers; zero of 4 workspace rates as constants; zero of 3 crafting commission tiers; zero of 5 mentor fee bands; no DB migration for canonical price tables; no agent tool `get_merchant_price`. (Hollow material values audit findings are owned by M9.4 below.)

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

### Audit Status (Sprint-006) — M9.3

<!-- see audit/phase-9-economy.md §Quest Reward Tiers -->

**Status: DESIGNED↔aspirational.**

Quest reward processing ships at `apps/agent/quest_tools.py:138-167` (handles XP rewards via `on_complete.get("xp", 0)`). `content/quests.json` ships 3 quests (`greyvale_anomaly`, `investigate_aldric`, `defend_millhaven`) with stages and rewards arrays. The **data plumbing exists**; the **spec-tier classification** (Tier 1/2/3 ranges, currency_reward field, `validate_quest_reward` helper) does not.

---

### Milestone 9.4 — Loot-side Economy (NEW)

> **Promoted from Sprint-003 audit decision `m9-4-loot-economy-status`.** Owns the encounter_roles §Loot Modifiers framework + gm_economy §Hollow Material Values + §Currency Drops from Combat.

**Goal:** Implement the loot-side framework that scales currency drops, material drops, and Boss bonus loot by encounter role (Minion/Standard/Elite/Boss/Named) × creature category (Beast/Humanoid/Hollow/Undead/Construct) × tier × biome.

**Inputs:** M9.1 (currency model), encounter_roles overlay (Phase 4 M4.7 — proposed in sprint-003 capstone), Phase 7 M7.1 (creature stat block schema with `role` field).

**Deliverables:**
- Pure function: `calculate_currency_drop(creature_category, role, tier, biome)` → coins dropped (cp/sp/gc)
- Currency drop rules per gm_economy §Currency Drops from Combat (5 category rules: beasts/constructs 0, humanoids Tier×1d6 sp, Hollow Drift 0, Hollow Rend+ 15% chance, undead 25%)
- Role modifiers: Minions never drop currency; Bosses drop 2× plus tier-scaled bonus
- Hollow Material Values: 4-tier price table (Drift 5-15 sp / Rend 50-100 sp / Wrack 200-500 sp / Named fragments 500 sp fixed)
- Material sell value table: role-keyed (Minion / Standard / Elite / Boss) × material category, per encounter_roles spec
- Boss bonus loot: context-driven loot slot per Decision 80 (in-fiction reward tied to encounter context, not creature)
- Agent tool: `resolve_combat_loot(combat_id)` → currency + materials + bonus-loot bundle

**Acceptance criteria:**
- [ ] Currency drops match spec category × role matrix across all 5 categories × 5 roles
- [ ] Hollow material values match the 4-tier spec table
- [ ] Material sell values match encounter_roles spec (role-keyed)
- [ ] Boss bonus loot is context-driven, not creature-driven (per Decision 80)
- [ ] Tier×biome currency yield matrix is correct (covers all 4 tiers × ≥6 biomes)
- [ ] `calculate_currency_drop` is pure; tests cover every category × role × tier combo
- [ ] Material sell value lookup matches spec for every role × material category cell

**Key references:**
- *Game Mechanics Economy — Currency Drops from Combat*
- *Game Mechanics Economy — Hollow Material Values*
- *Game Mechanics Encounter Roles — Loot Modifiers (Currency Drop Rules + Material Sell Values + Boss bonus loot)*

### Audit Status (Sprint-006) — M9.4

<!-- see audit/phase-9-economy.md §Currency Drops + §Hollow Material Values + audit/phase-encounter-roles.md -->

**Status: NOT_SHIPPED.** No `calculate_currency_drop` symbol, no role-keyed material sell tables, no Boss-bonus loot framework, no tier×biome currency yield matrix. Substrate dependencies (Phase 4 M4.7 encounter_roles + Phase 7 M7.1 creature `role` field) are also NOT_SHIPPED per sprint-003 audits.

---

### Milestone 9.5 — Faction Reputation Pricing (NEW)

**Goal:** Implement the 6-tier faction reputation ladder + per-tier price modifiers + service-refusal gating + reputation-granting economic actions + faction-exclusive access framework.

**Inputs:** M9.1 (price tables), M9.2 (pricing engine — provides the disposition modifier this stacks with), Phase 6 M6.1 (NPC schema with `faction: string` field — BUILT per phase-6 audit), Phase 8 faction system.

**Deliverables:**
- 6 reputation tiers with thresholds (Hostile -10 / Unfriendly -5 / Neutral 0 / Friendly +5 / Trusted +15 / Honored +25)
- Per-tier price modifier table (Unfriendly +15% / Neutral 1.0× / Friendly -5% / Trusted -10% / Honored -15%; Hostile = service refusal)
- Combined disposition × faction modifier table (5×6 = 30 cells per spec L32-38)
- Service availability gating per tier (Hostile = none; Unfriendly = basic only; Neutral = full; Friendly = +discounted consumables + bounty board; Trusted = +faction equipment + commissions + workspace; Honored = +priority restock + masterwork + intelligence)
- 5 reputation-granting economic actions (sell rare materials +1, commission faction equipment +1, donate +1/25sp, fulfill bounty +1 to +3, supply rare crafted +2) with caps (max +3/week from economic activity; once-per-day per action type; cap at Trusted +15, Honored is quest-only)
- 5 reputation-damaging actions (sell secrets, trade restricted, fence stolen, refuse bounty, undercut [Phase 2+])
- Detection-gated negative consequences (Insight checks by faction NPCs, faction intelligence networks via simulation tick)
- `ReputationTier.price_modifier: number` schema extension on Faction.reputation_tiers
- Reputation persistence pipeline: read/write `player_reputation.data->reputation_value` (table BUILT but dormant)
- Pure function: `compute_faction_modifier(player_id, merchant_faction_id)` → modifier float
- Agent tools: `grant_reputation(player_id, faction_id, amount, reason)`, `check_faction_service_available(player_id, merchant_id, service_type)` → bool
- DM narration templates: 5 tier-standing patterns + reputation-shift narration (consequence-not-transaction framing)

**Acceptance criteria:**
- [ ] Faction.reputation_tiers schema extended with `price_modifier: number`; 4 shipped factions backfilled with spec values
- [ ] `player_reputation` table reads/writes for reputation_value
- [ ] Combined disposition × faction 5×6 matrix matches spec exactly
- [ ] Service-refusal gating returns correct availability for each (faction_tier × service_type) cell
- [ ] All 5 grant actions adjust reputation correctly with caps + cooldowns enforced
- [ ] All 5 loss actions adjust reputation when detected; no adjustment when undetected
- [ ] Insight check during trade interactions can detect reputation-damaging actions
- [ ] Tests cover every cell of the matrix, every grant/loss action, all caps and cooldowns, detection gates

**Key references:**
- *Economy — Faction Reputation Pricing* (`docs/game_mechanics/economy/faction_reputation_pricing.md`)
- *Game Mechanics Decisions 82-86*

### Audit Status (Sprint-006) — M9.5

<!-- see audit/phase-9-faction-pricing.md -->

**Status: DESIGNED↔confirmed at substrate, NOT_SHIPPED at pipeline.**

Strongest BUILT substrate of any Phase 9 subsystem. `Faction` interface ships `reputation_tiers: Record<string, ReputationTier>` (`packages/shared/src/entities/faction.ts:1-21`) with `{threshold, effects[]}`. `content/factions.json` ships 4 factions (accord_guild, aelindran_diaspora, independent, temple_authority), **each populating all 6 spec tiers with EXACT spec thresholds** (-10/-5/0/+5/+15/+25 verified on accord_guild). `factions` + `player_reputation` tables BUILT (migration 001:57-66, 135-143) + `idx_player_reputation_faction` (002:5).

What does NOT ship: zero code reads or writes `player_reputation`; no `ReputationTier.price_modifier: number` field; no `compute_faction_modifier` function; zero of 5 grant + 5 loss handlers; no caps/cooldowns; no service-refusal gating; no faction-tier-gated inventory; no narration templates. The `effects: string[]` field carries **narrative prose only** (e.g. `"banned from guild hall"`), not numerical modifiers.

Content/spec divergence: spec uses **Thornwatch + Merchant Guild** as worked examples; shipped roster is accord_guild + aelindran_diaspora + independent + temple_authority. **Capstone follow-up:** decide whether to backfill Thornwatch in content or rewrite spec to use shipped faction ids.

---

### Milestone 9.6 — Merchant Inventory & Restock (NEW)

**Goal:** Implement the three-tier stock model (always-stocked / limited / unique) + 7 spec-named inventory pools + settlement size×personality stock multipliers + daily restock at dawn + merchant gold pool + buyback limits + consignment.

**Inputs:** M9.1 (price tables), M9.2 (pricing engine), M9.5 (faction reputation — affects restock + faction-restricted inventory), Phase 6 M6.1 (NPC schema with `inventory_pool: string | null` — BUILT but unused).

**Deliverables:**
- Three-tier stock model: Tier 1 always-stocked (trivial supplies); Tier 2 limited (refills daily); Tier 3 unique (daily probability check or weekly rotation)
- Tier classification on `Item` schema OR on pool entries
- 7 inventory pools (`general_supplies`, `weapons_armor_basic`, `weapons_armor_quality`, `alchemical_supplies_common`, `exotic_goods`, `jeweler_goods`, `black_market`)
- Pool schema with `tier_1_items[]` + `tier_2_items[{item_id, quantity_by_settlement: {hamlet, village, town, city}}]` + `tier_3_items[{item_id, settlements, presence_chance, restock_check}]` (replace shipped flat-list shape)
- 5 settlement size multipliers (Hamlet 0.25× / Village 0.5× / Town 1.0× / City 1.5× / Capital 2.0×)
- 6 personality modifiers (Prosperous +25% / Struggling -50% / Military +50% weapons /-25% civilian / Trade Hub +25% all / Isolated -50% T2 + 25% price markup / Cursed -75%)
- `Location.size: enum(hamlet|village|town|city|capital)` + `Location.personality: enum[]` schema extension
- `merchant_state` table: `current_inventory`, `current_gold`, `max_gold`, `last_restock_tick`, `buyback_history`, `consigned_items` (Redis + PostgreSQL backing)
- Daily gold allocations (5 settlement × 4 merchant-type matrix per spec L286-292)
- 4 buyback limits (Common weapons 3/day, Common consumables 5/day, Quality 2/day, Unique 1/day)
- Consignment at Friendly+ disposition (1d4 day delivery, 10% commission)
- Traveling merchant entity type (1-2 day visits, +10% buy / -10% sell)
- Pure functions: `daily_restock_at_dawn()`, `attempt_purchase(player_id, merchant_id, item_id, quantity)`, `attempt_sale(player_id, merchant_id, item_id, quantity)`
- Agent tools: `query_merchant_inventory`, `purchase_item`, `sell_item`, `consign_item`
- DM narration templates: shop-entry (3-4 highlights), per-item-inquiry by phase, selling, buyback-limit, restock narration

**Acceptance criteria:**
- [ ] All 7 spec pools ship in `content/inventory_pools.json` with tiered structure + settlement-keyed quantities
- [ ] `inventory_pool` field populated on every merchant NPC in `content/npcs.json`
- [ ] Location.size + Location.personality schema extensions; all settlements in `content/locations.json` populated
- [ ] 5×6 size×personality stock multiplier matrix matches spec for both inventory and gold pool
- [ ] `merchant_state` table reads/writes for current_inventory + current_gold + buyback_history + consigned_items
- [ ] `daily_restock_at_dawn` resets all merchants per spec algorithm; matches deterministic output for fixed seed
- [ ] `attempt_purchase` enforces stock check + gold check + capacity check; emits sink_event (M9.8 dep)
- [ ] `attempt_sale` enforces buyback limit + merchant gold pool; offers partial purchase / refusal / consignment at correct disposition gates
- [ ] Consignment expires after 1d4 days; expired items return to consignor
- [ ] Traveling merchant entity instantiates with 1-2 day visit + rotating feature item
- [ ] Tests cover every cell of size×personality matrix, every buyback-limit edge case, consignment expiration paths, traveling merchant visit lifecycle

**Key references:**
- *Economy — Merchant Inventory & Restock* (`docs/game_mechanics/economy/merchant_inventory_restock.md`)
- *Game Mechanics Decisions 87-95*

### Audit Status (Sprint-006) — M9.6

<!-- see audit/phase-9-restock.md -->

**Status: DESIGNED↔aspirational at substrate, NOT_SHIPPED at pipeline.**

Substrate BUILT: `inventory_pools` table (migration 001:84-91); 4 content pools (`market_general`, `grimjaw_weapons`, `temple_supplies`, `millhaven_supplies`) with schema-divergent flat-list shape; `Npc.inventory_pool: string | null` field on schema (0 of 14 NPCs populate it); `player_inventory` table actively used by `apps/agent/db_queries.py:120,187` + `apps/agent/db_mutations.py:135,156`; narrative-only `add_to_inventory` + `remove_from_inventory` agent tools at `apps/agent/inventory_tools.py:24,105`.

**Schema divergence:** spec pool shape is type-keyed with tier classification + settlement-keyed quantities. Shipped pool shape is location/merchant-keyed flat list with `{item_id, quantity, price}`. Capstone follow-up: restructure content to spec shape OR adapt spec to shipped shape.

**Pool prices vs Item.value_base:** `market_general` + `grimjaw_weapons` pools have prices that exactly match `Item.value_base`. `temple_supplies` carries -10% discounts. `millhaven_supplies` carries +20-67% markups (directionally consistent with spec's Isolated personality +25% but exceeds nominal magnitude). When the pricing engine lands, decide between (a) delete pool.price + compute from value_base via formula, (b) rename to `base_price_override`, (c) hybrid.

What does NOT ship: 0 of 5 settlement size multipliers (Location.size field absent — `region_type` ships with values {city, wilderness, dungeon}, 0 of 6 personality traits in tags); 0 merchant_state machine; 0 daily_restock function; 0 attempt_purchase/sale enforcing function; 0 traveling merchant; 0 consignment; 0 of 9 decisions 87-95 encoded.

---

### Milestone 9.7 — Supply & Demand Engine (NEW)

**Goal:** Implement event-driven price dynamics — 15 standard economic events × 3-phase lifecycle (Active / Recovery / Resolved) × multiplicative stacking with 0.5×–3.0× clamp × economic-tag-based item matching × DM narration patterns.

**Inputs:** M9.1 (base prices), M9.2 (pricing engine — provides the event modifier hook), M9.6 (merchant state — needs price cache invalidation), Phase 7 world simulation (event lifecycle integration).

**Deliverables:**
- 11-tag economic taxonomy (`healing`, `anti-hollow`, `divine`, `weapons`, `armor`, `food`, `travel`, `luxury`, `crafting_material`, `imported`, `military`)
- `Item.economic_tags: string[]` field on schema (separate from narrative tags) OR tag-inheritance convention from material composition
- 3-phase event lifecycle: Active (full multiplier) / Recovery (linear decay to 1.0× over half-active-duration, min 2 days) / Resolved (no effect)
- 15 standard economic events in `content/events.json` (6 demand-driven: Hollow Incursion / Bandit Activity / Disease Outbreak / War / Religious Pilgrimage / Refugee Influx; 5 supply-driven: Trade Route Disrupted / Mine Closure / Forest Corruption / Drought / Faction Embargo; 4 surplus: Bumper Harvest / Successful Mining Operation / Festival / Faction Surplus)
- Event-instance schema in `world_events_log.data` JSONB: `{event_template, phase, started_at, phase_started_at, active_duration_seconds, recovery_duration_seconds, affected_regions, active_multipliers}`
- 0.5×–3.0× hard price clamp (cross-cuts M9.2 calculate_price)
- Multiplicative stacking: `event_modifier = product of all active event multipliers` for matching tags; once-per-event-per-item rule (strongest applicable tag wins per event)
- Pure functions: `compute_event_modifier(item, region)`, `compute_recovery_multipliers(event)`
- Simulation tick: `economy_simulation_tick()` every 10 minutes — updates event lifecycle, instantiates new events from templates with met trigger conditions, invalidates Redis price cache for affected regions
- Redis price cache: `region:{region}:prices` with 60s TTL, invalidated on event state change
- DM narration templates: event-onset (per event type), per-phase item-inquiry, cross-settlement awareness (suggest travel for better prices), player-intervention acknowledgment

**Acceptance criteria:**
- [ ] All 15 standard events ship in `content/events.json` with `type: "economic"` and active_multipliers
- [ ] Three-phase lifecycle transitions correctly (Active → Recovery on trigger condition met / time expired; Recovery → Resolved on duration elapsed)
- [ ] Linear recovery decay matches spec equation across at least 4 sample events
- [ ] Multiplicative stacking + clamp produces correct prices for the spec's worked example (Healing Potion 25 sp → 39 sp with Hollow Incursion + Disease Outbreak + Refugee Influx + Friendly disposition + Trusted faction)
- [ ] Once-per-event-per-item tag matching: an item with both `anti-hollow` and `divine` tags gets the strongest multiplier from a Hollow Incursion event, not both stacked
- [ ] `economy_simulation_tick` updates lifecycle + instantiates new events + invalidates cache deterministically
- [ ] Redis price cache hits/misses correctly with 60s TTL and event-driven invalidation
- [ ] Tests cover 4 worked examples + tag-matching edge cases + clamp boundaries + phase transitions

**Key references:**
- *Economy — Supply & Demand Engine* (`docs/game_mechanics/economy/supply_demand_engine.md`)
- *Game Mechanics Decisions 96-104*

### Audit Status (Sprint-006) — M9.7

<!-- see audit/phase-9-supply-demand.md -->

**Status: DESIGNED↔aspirational at substrate, NOT_SHIPPED at engine.**

Substrate BUILT for narrative news feed (not for price impact): `world_events_log` table (migration 001:184-189); 8 records in `content/events.json` (4 scripted + 3 world_event + 1 god_whisper — none `type: "economic"`); `apps/agent/db_mutations.py:228` writes; `apps/agent/world_news.py:39,52-55` reads for player catch-up summaries. The JSONB blob could theoretically carry the spec's event-instance schema, but **no shipped code reads or writes that shape**.

Tag substrate partial: `Item.tags: string[]` ships as a single narrative+economic tag array. **1 of 11 spec economic tags (`healing`) appears organically** on 3 items (healing_potion, antidote_basic, restoration_salve). The other 10 economic tags do not appear consistently.

What does NOT ship: 0 of 15 economic events; 0 phase transitions; 0 multiplier-stacking; 0 clamp; `compute_item_price` + `compute_recovery_multipliers` + `economy_simulation_tick` all absent; no Redis price cache; 0 narration templates; 0 of 9 decisions 96-104 encoded.

---

### Milestone 9.8 — Gold Sink Ledger (NEW)

**Goal:** Implement the 8-category sink framework + sink_event_log infrastructure + 5 gap-analysis additions (companion equipment, bribery, travel tolls, NPC gifts; property deferred to Phase 2+) + magnitude analysis telemetry.

**Inputs:** M9.1 (gold field on player), M9.2 (pricing engine — most sinks consume merchant prices), M9.5 (faction donation sink), M9.6 (consignment + traveling merchant + buyback-limit sinks), M9.7 (supply/demand event modifiers feed into sink magnitudes), M9.9 (faucet event logging — symmetric infrastructure).

**Deliverables:**
- 8-category sink framework as code constants (Maintenance / Subsistence / Combat / Progression / Crafting / Service / Lifestyle / Endgame)
- `sink_event_log` table: `{id, player_id, sink_category, sink_type, item_id, amount_sp, context, timestamp}`
- `add_gold` / `consume_gold` / `attempt_charge` mutation surface on player.gold (currently one-write-no-read)
- `consume_item` agent tool that decrements inventory + emits sink_event when player uses a consumable
- `apply_rest(rest_type, lodging_quality)` extension: gates +1 quality bonus on payment + emits sink_event for 1sp/5sp/15sp lodging tiers
- 5 reputation-granting donation/commission/supply handlers (cross-ref M9.5)
- 4-tier repair cost table (Common 2sp / Uncommon 10sp / Rare 50sp / Legendary 200+sp; depends on Phase 5 durability M5.4)
- 8 NPC service handlers (Heal Wounds / Cure Poison / Dispel Corruption / Remove Curse / Greater Restoration / Resurrection / Identify / Research / Translate; cross-ref M9.2)
- Bribery system (Gap 2): NPC accept threshold = f(role, disposition, faction_loyalty, stakes); +failed-bribe disposition penalty; refusal as alternative outcome
- Travel toll system (Gap 3): ferry/bridge/city-entry/mountain-pass tolls with free-alternative constraint (long route, faction relationship, or skill check) per Decision 110
- Companion equipment maintenance (Gap 1): half player gear cost per Decision 112
- NPC gift system (Gap 5): `appreciated_gifts: string[]` field on Npc schema + accept-gift mechanic + disposition shift
- Magnitude analysis aggregator: per-category drain rolled up over 30-day window
- Faucet/sink balance check (cross-ref M9.9): quest tier rewards vs typical sink drain → expected ~net +50-150 sp per session

**Acceptance criteria:**
- [ ] `sink_event_log` table writes occur on every gold-removal path; reads aggregate by category
- [ ] `player.gold` correctly debits on every spec sink (consume potion → 25 sp; pay for fine room → 15 sp; commission repair → 50 sp; etc.)
- [ ] All 8 sink categories enumerated as constants; per-category aggregator returns correct totals
- [ ] `consume_item` decrements inventory + emits sink_event matching item.value_base
- [ ] `apply_rest(rest_type, lodging_quality)` gates +1 quality bonus on payment and emits sink_event
- [ ] Bribery: NPC accept threshold respects role × disposition × faction; refused bribe applies disposition penalty
- [ ] Travel tolls all have a free alternative per Decision 110; toll-bypass via skill check or faction relationship works
- [ ] Companion equipment repair costs half of equivalent player gear (Decision 112)
- [ ] `appreciated_gifts` field on Npc + gift-acceptance mechanic shifts disposition correctly
- [ ] Magnitude analysis correctly aggregates per-category drains over 30-day window
- [ ] Tests cover every sink category × every spec sink type

**Key references:**
- *Economy — Gold Sink Ledger* (`docs/game_mechanics/economy/gold_sink_ledger.md`)
- *Game Mechanics Decisions 105-113*

### Audit Status (Sprint-006) — M9.8

<!-- see audit/phase-9-gold-sink.md -->

**Status: NOT_SHIPPED.** This is a **consolidation audit** — most sinks inherit NOT_SHIPPED from their source subsystems (Phase 5 durability, Phase 6 mentors, M9.5 faction donations, M9.6 consignment + traveling merchant, M9.2 NPC services + workspace + commissions).

What ships beyond inherited substrate: `player.gold: int` field set at creation (`creation_rules.py:257`) but **never mutated** by any code (zero increment/decrement matches). `apps/agent/rest_mechanics.py` ships pure-function `apply_short_rest` / `apply_long_rest` / `apply_rest` — rest itself BUILT — but **lodging-cost gating NOT_SHIPPED**: rest takes no `lodging_quality` parameter and emits no sink event. 6 consumable items in `content/items.json` (healing_potion, antidote_basic, holy_water, rations_basic, millhaven_provisions, restoration_salve) — content exists but **no `consume_item` hook fires sink emission** when one is used.

What does NOT ship: 0 sink_event_log table; 0 of 8 category constants; 0 magnitude analysis aggregator; 0 of 5 gap additions (companion gear / bribery / tolls / NPC gifts / property which is Phase 2+); 0 of 9 decisions 105-113 encoded.

---

### Milestone 9.9 — Inflation Targets & Controls (NEW)

> **Phase scope:** This milestone defines targets and controls for both Phase 1 (single-player) and Phase 2+ (multiplayer/MMO). **Phase 1 needs only the per-character balance framework and analytics infrastructure**; Phase 2+ adds global economy controls, god-agent economic intervention, and seasonal event systems.

**Goal:** Implement faucet_event_log + aggregate metrics + 8-band wealth-by-level curve + god-agent economic intervention substrate (heartbeat hook) + 1-2 seasonal events as proof-of-concept + parameter tuning capability.

**Inputs:** M9.1 (currency), M9.3 (quest rewards = primary faucet), M9.4 (currency drops = secondary faucet), M9.6 (loot/material sales = tertiary faucet), M9.8 (sink_event_log — symmetric infrastructure), Phase 8 patron heartbeat system.

**Deliverables (Phase 1 — required):**
- `faucet_event_log` table: `{id, player_id, faucet_category, faucet_type, quest_id?, item_id?, amount_sp, context, timestamp}`
- 8 faucet categories enumerated (quest_reward, loot_sale, material_sale, crafted_sale, faction_bounty, service_income, currency_drop, consignment_payout)
- Faucet-event emission hooked into shipped surfaces: quest reward handler (`apps/agent/quest_tools.py`), sale/transfer paths (`apps/agent/inventory_tools.py`), currency drop resolver (M9.4)
- 8-band wealth-by-level curve constants table (L1: 10sp → L19-20: 6,000-15,000sp)
- Per-session balance target tracker: net +50-150 sp typical (computed from faucet - sink event diff per session)
- 5 aggregate metrics × rolling windows (per-session net, wealth-by-level snapshot, faucet category distribution, sink category distribution, net wealth velocity by level)
- God-agent `evaluate_economic_state` consideration in patron heartbeat: reads aggregate metrics, identifies drift, picks affected god, emits economic event + whisper
- Parameter tuning config: server-side editable values for quest reward tier ranges, sink magnitudes, currency drop formulas

**Deliverables (Phase 2+ — stub now, activate later):**
- 4 ratio-target window thresholds (24h 0.7-1.4 / 7d 0.85-1.2 / 30d 0.95-1.1 / 90d 0.98-1.05) with escalation policy
- Per-god economic intervention handlers (Mortaen tribute / Aelora vision / Veythar research / Kaelen conflict — see honesty note on Aelora vs spec's "Aelindra")
- 6 seasonal events (Lantern Festival / Forge Day / Veil Wane / Veil Wax / Harvest Time / Long Dark) with calendar triggers
- 6-step inflation control loop (data ingestion → aggregation → drift detection → escalation by window → effect propagation → narration)

**Acceptance criteria (Phase 1):**
- [ ] `faucet_event_log` table writes occur on every gold-source path
- [ ] All 8 faucet categories enumerated as constants
- [ ] 8-band wealth curve encoded as a config table (JSON or DB) so it's tunable without code change
- [ ] Per-session balance tracker returns correct net for at least 5 simulated sessions
- [ ] All 5 aggregate metrics compute correctly over rolling windows
- [ ] `evaluate_economic_state` heartbeat consideration registers; emits a stub event when drift detected (no real-time intervention in Phase 1)
- [ ] 1-2 seasonal events authored as proof-of-concept content (recommended: Forge Day OR Harvest Time)
- [ ] Tests cover faucet emission on every shipped surface + 5 aggregate metric computations + heartbeat trigger condition

**Key references:**
- *Economy — Inflation Targets & Controls* (`docs/game_mechanics/economy/inflation_targets_controls.md`)
- *Game Mechanics Decisions 114-121*
- *Game Mechanics Patrons* (heartbeat system; phase-8 audit)

### Audit Status (Sprint-006) — M9.9

<!-- see audit/phase-9-inflation.md -->

**Status: DESIGNED at god substrate, NOT_SHIPPED at inflation pipeline.**

Substrate BUILT for god-whisper generation (not inflation): `content/gods.json` ships 10 gods including `mortaen`, `veythar`, `kaelen` (matches spec's named economic gods); `god_whispers` table BUILT (migration 009); `god_whisper_generator.py:16` ships `generate_god_whisper`; `async_worker.py:396-426` invokes it on patron-id triggers. **But the trigger pipeline is patron-id-driven, not economic-state-driven** — no `evaluate_economic_state` heartbeat consideration.

**God roster divergence:** spec names **Aelindra** (Preservation/Memory/Value) as an economic-intervention god. **Aelindra is NOT in the shipped god roster** — closest analogue is `aelora` (Civilization/commerce/crafting/community). Faction `aelindran_diaspora` exists separately. Capstone follow-up: rename `aelora` → `aelindra` OR update spec to use shipped `aelora`.

What does NOT ship: 0 faucet_event_log; 0 wealth_curve constants; 0 aggregate metrics; 0 ratio-window enforcement; 0 of 6 seasonal events (Keldaran faction also missing from `content/factions.json` — Forge Day has no cultural backing); 0 parameter tuning config; 0 of 8 decisions 114-121 encoded.

---

### Milestone 9.10 — P2P Trade Infrastructure (NEW [Phase 2+])

> **Phase scope:** Player-to-player trade is **Phase 2+ deferred**. Phase 1 is single-player, so trade mechanics do not exist yet. This milestone scopes only the **Phase 1 supporting-infrastructure items** spec L178-194 says should ship now to avoid expensive Phase 2 retrofitting.

**Goal (Phase 1 only):** Ship 4 supporting-infrastructure items so Phase 2+ trade design has the substrate ready.

**Inputs:** M9.1 (currency), M9.8 (sink_event_log — transfer is a special event type), M9.9 (faucet_event_log), Phase 6 M6.1 (NPC schema + Location schema for settlement-aware queries).

**Deliverables (Phase 1):**
- **Item provenance:** typed `provenance: ProvenanceEvent[]` field on Item (or sibling `item_history` table keyed on per-instance UUID). Replaces current free-text `source: str` parameter on `add_to_inventory`. Each event captures `{actor_type, actor_id, action, timestamp, context?}`. Migration converts existing source strings into 1-event seed histories.
- **Per-instance item identity:** `item_instance_id UUID` column (or `data.instance_id` convention) on `player_inventory` so the provenance trail has a per-copy anchor (current PK is `(player_id, item_id)` on template id).
- **Atomic transaction primitives:** `atomic_p2p_transfer(from_player, to_player, items, gold)` function wrapping inventory mutations + gold debit/credit in a single asyncpg transaction. Uses existing `conn: asyncpg.Connection | Pool | None` parameter pattern (BUILT across 22 sites in `apps/agent/db_mutations.py`).
- **Settlement-aware APIs:** `Location.settlement_id: string` field + `Settlement` entity type OR tag→settlement_id mapping convention. Enables `same_settlement(p1, p2) -> bool` query.
- **Transaction logging schema:** P2P transfer event type integrated into the unified faucet/sink event log (M9.8 + M9.9). Logged at 0 sp from sink perspective in Phase 1; activated for real values in Phase 2+.

**Deliverables (Phase 2+ — stub now, activate later):**
- Direct trade flow (same-location, atomic exchange via DM-facilitated transaction, free in non-faction territory per Decision 128)
- Remote trade flow (faction couriers, transport fees, in-transit state, loss/theft risk, insurance)
- Auction house design (deferred to Phase 2 design time per Decision 127)
- 4 fee structures (faction transaction tax, transport fees, auction fees, witness fees) + tax-avoidance gameplay (smuggling/frontier markets)
- 6 anti-fraud guardrails (atomic transactions BUILT in Phase 1; transaction logs, velocity limits, value asymmetry detection, new-account restrictions, item provenance — Phase 1 substrate; full enforcement Phase 2+)

**Acceptance criteria (Phase 1 only):**
- [ ] `provenance: ProvenanceEvent[]` field on Item (or sibling table); migration converts existing `source: str` data
- [ ] Per-instance UUID identity on `player_inventory` rows (PK changes or data field convention)
- [ ] `atomic_p2p_transfer` function wraps multi-mutation in single transaction; rollback on any failure
- [ ] `Location.settlement_id` schema extension; all locations in `content/locations.json` populated
- [ ] `same_settlement(p1, p2)` returns correct bool for cross-settlement and same-settlement pairs
- [ ] Unified event log accepts `transfer_event` rows with `from_player_id` + `to_player_id` (logged at 0 sp in Phase 1)
- [ ] Tests cover provenance migration + per-instance UUID generation + atomic-transfer rollback + same_settlement edge cases

**Key references:**
- *Economy — Player-to-Player Trade* (`docs/game_mechanics/economy/game_mechanics_p2p_trade.md`)
- *Game Mechanics Decisions 122-128*

### Audit Status (Sprint-006) — M9.10

<!-- see audit/phase-9-p2p-trade.md -->

**Status: DESIGNED↔aspirational on 2 of 4 Phase 1 infrastructure items; NOT_SHIPPED on 2.**

Phase 1 supporting infrastructure (the only Phase 9 surface in scope):
1. **Item provenance — DESIGNED↔aspirational.** `add_to_inventory(item_id, quantity, source: str)` BUILT at `apps/agent/inventory_tools.py:24-33` with free-text source (examples: "looted from goblin", "purchased from merchant"). Structured trail + per-instance UUID NOT_SHIPPED.
2. **Atomic transaction primitives — DESIGNED↔aspirational.** Asyncpg `conn` parameter plumbing BUILT across 22 mutation sites in `apps/agent/db_mutations.py`. `atomic_p2p_transfer` primitive itself NOT_SHIPPED.
3. **Settlement-aware APIs — NOT_SHIPPED.** Player→location BUILT (`update_player_location` writes `players.data->location_id`); `Location.settlement_id` field absent (cross-ref M9.6 honesty note).
4. **Transaction logging schema — NOT_SHIPPED.** Inherits M9.8 + M9.9 — neither sink_event_log nor faucet_event_log ships.

Phase 2+ trade mechanics intentionally NOT_SHIPPED. 0 of 7 decisions 122-128 encoded. **No multiplayer infrastructure exists** in code (0 grep matches).

---

## Decision log

- **`m9-rewrite-single-file`** (capstone story-008): 09_economy.md keeps single-file shape with 10 numbered milestones (M9.1-M9.10). Rationale: single source of truth, matches Phase 5/6 organization, simpler M7 README dep graph. Total acceptance items 21 → ~80.
- **`m9-decisions-73-128-consolidated`** (capstone story-008): commit `884adeb` extracted decisions 73-128 (56 entries) from inlined source spec sections into the canonical `game_mechanics_decisions.md` log (was: 1-72, now: 1-128). This was a consolidation gap, not a documentation gap — decisions always existed where designed. Audit framing slip recorded as concern `d47df1654ba0`.
- **`m9-4-loot-economy-status`** (sprint-003 capstone, deferred): now landed as M9.4 Loot-side Economy.

## Cross-cutting follow-ups for future sprints

See `audit/README.md` Sprint-006 follow-up candidates section for the full list. Highlights:

- **M9.2 disposition_modifiers field collision** (rename or add `price_disposition_modifiers`). Schema decision required before M9.2 ships.
- **M9.5 faction content reconciliation** (Thornwatch + Merchant Guild + Keldaran missing from `content/factions.json`).
- **M9.6 inventory_pools schema migration** (flat-per-merchant → typed-tier-with-settlement-quantity).
- **M9.6 + M9.10 Location.settlement_id field** (shared blocker — multi-layer gap).
- **M9.7 Item.economic_tags field** (separate from narrative tags) — 1 of 11 spec tags appears organically (`healing`).
- **M9.8 player.gold one-write-no-read pattern** — needs `add_gold` / `consume_gold` / `attempt_charge` mutation surface alongside the read path.
- **M9.9 god roster: Aelora vs spec's Aelindra** — rename or accept the mapping.
- **M9.10 per-instance item UUID** — current `(player_id, item_id)` PK is on template id, blocks per-copy provenance.
