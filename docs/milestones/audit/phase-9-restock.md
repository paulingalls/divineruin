# Phase 9 Audit — Economy / Merchant Inventory & Restock (Sprint-006 story-004)

Sprint-006 / Milestone 6 (story-004). Read-only audit of `docs/game_mechanics/economy/merchant_inventory_restock.md` (646 lines, 1 H2 with 9 major subsections) against shipped code in `apps/agent/`, `apps/server/src/`, `packages/shared/src/entities/`, `content/`, and `scripts/migrations/`. Status legend (matches sprint-004 audit/README.md L49-58): **BUILT** = code present and matches spec; **DESIGNED** = spec well-defined and partial code exists, but the symbol/feature is missing, renamed, or diverges; **NOT_SHIPPED** = no implementation found. Sibling sprint-006 audit files: `phase-9-economy.md` (story-001), `phase-9-supply-demand.md` (story-002), `phase-9-faction-pricing.md` (story-003).

Verified-at: 4046efc4fc19d9c9c8db80a83b0d0a495f7bb012

## Summary

| Section | BUILT | DESIGNED | NOT_SHIPPED |
| --- | --- | --- | --- |
| Three-Tier Stock Model (Tier 1/2/3 classification) | 0 | 0 | 3 |
| Inventory Pools — Definitions (7 spec pools + content shape) | 0 | 2 | 7 |
| Stock Limits by Settlement (5 size multipliers + 6 personality modifiers) | 0 | 0 | 11 |
| Daily Restock Mechanics (process + frequency + disruption) | 0 | 1 | 3 |
| Merchant Gold Pool (allocations + mechanics + personality mods + buyback limits) | 0 | 0 | 8 |
| Special Inventory Categories (traveling / faction-restricted / quest-locked) | 0 | 1 | 5 |
| Voice-First Inventory Communication (DM narration patterns) | 0 | 0 | 6 |
| Implementation Reference (inventory_pools schema + merchant_state + daily_restock + purchase + sale) | 0 | 2 | 4 |
| Design Decisions 87-95 (9 design decisions) | 0 | 0 | 9 |

**Headline finding:** Merchant inventory + restock is **mostly NOT_SHIPPED**, but the inventory-pool substrate is partially BUILT with **divergent schema**. What ships: `inventory_pools` table (`scripts/migrations/001_initial_schema.sql:84-91`), 4 content pools in `content/inventory_pools.json` (`market_general`, `grimjaw_weapons`, `temple_supplies`, `millhaven_supplies`), `Npc.inventory_pool: string | null` field on shared schema (`packages/shared/src/entities/npc.ts:34`), `player_inventory` table actively used by `apps/agent/db_queries.py:120,187` and `apps/agent/db_mutations.py:135,156`, and the narrative-only `add_to_inventory`/`remove_from_inventory` agent tools (`apps/agent/inventory_tools.py:24,105`) that the DM calls to record transactions. What does NOT ship: zero of 3 stock tiers (no Tier 1/2/3 classification on items or pools); zero of 7 spec-named pools (4 shipped pools are location/merchant-named, not type-named); zero of 5 settlement size multipliers; zero of 6 personality modifiers; zero merchant state machine (no `merchant_state` table, no `current_inventory`/`current_gold`/`buyback_history`/`consigned_items` tracking); zero `daily_restock_at_dawn` function; zero `attempt_purchase`/`attempt_sale` pricing-enforcing functions; zero of 4 traveling-merchant mechanics; zero of 3 quest-lock or faction-restricted gates; zero of 6 DM narration patterns; zero of 9 design decisions encoded as constants.

**Honesty note 1 — `inventory_pools` schema diverges from spec.** The shipped pool shape is `{id, name, location, type, restock_interval_hours, items: [{item_id, quantity, price}]}` — a **flat per-merchant item list with fixed quantities and embedded prices**. Spec L453-480 defines `{id, tier_1_items: [...], tier_2_items: [{item_id, quantity_by_settlement: {hamlet, village, town, city}}], tier_3_items: [{item_id, settlements, presence_chance, restock_check}]}` — a **type-based pool reusable across merchants with tiered structure and settlement-size quantity ranges**. The two models are structurally incompatible. Capstone must decide: (a) restructure content pools to spec shape and add a per-merchant binding, (b) change spec to match shipped shape, or (c) introduce an adapter layer. The schema substrate is BUILT; the spec's logical model is NOT_SHIPPED.

**Honesty note 2 — `Npc.inventory_pool` is BUILT on the schema but unpopulated in content.** `npc.ts:34` ships `inventory_pool: string | null` as a typed field. **Zero of the NPCs in `content/npcs.json` set `inventory_pool` to non-null** (`python3 -c "import json; print(sum(1 for n in (json.load(open('content/npcs.json'))['npcs'] if isinstance(json.load(open('content/npcs.json')),dict) else json.load(open('content/npcs.json'))) if n.get('inventory_pool'))")` → 0). The merchant→pool binding the schema supports is **not used**. The 4 pools in `content/inventory_pools.json` live as orphaned data. Cross-ref Phase 6 NPC audit: M6.1 NPC role archetypes are also NOT_SHIPPED, so merchant role-typing → inventory-pool assignment is a multi-layer gap.

**Honesty note 3 — Pool prices vs `Item.value_base` are partially co-authored, partially divergent.** Sampling cross-references: `market_general` and `grimjaw_weapons` pools carry `price` values that **exactly match** the `Item.value_base` in `content/items.json` (e.g., shortsword_basic=100 in both, longsword_guild=200 in both, chain_shirt=350 in both). `temple_supplies` carries discounted prices (healing_potion=45 vs item.value_base=50, -10%). `millhaven_supplies` carries marked-up prices (healing_potion=60 vs base=50 = +20%; torch_bundle=5 vs base=3 = +67%; rope_hemp=15 vs base=10 = +50%). The spec's merchant pricing formula (`base_price × disposition × faction × event × context` with 0.5×–3.0× clamp per story-002) would **compute** these markups at query time from a single `value_base`. The shipped model **bakes** the markup into the pool itself. **Capstone implication:** when the pricing engine lands, the per-pool `price` field must either be (a) deleted and replaced by formula-driven computation from `value_base`, (b) renamed to `base_price_override` to indicate spec-compliant intent, or (c) repurposed as a starting cache that the formula must validate against. Note: the Millhaven markups roughly match the spec's **Isolated personality** (+25% prices, spec L228) — suggesting the content author was modeling spec-aligned personality effects manually, item-by-item, instead of via a formula. This is **DESIGNED↔aspirational**: the *intent* maps to spec, the *mechanism* doesn't.

**Honesty note 4 — `Location` schema lacks settlement size and personality.** Spec's stock-limits and gold-pool tables (L208-235, L284-321) key on **5 size values (Hamlet/Village/Town/City/Capital) × 6 personality traits (Prosperous/Struggling/Military/Trade Hub/Isolated/Cursed/Corrupted)** = 30 base parameter combinations. The shipped `Location` interface (`packages/shared/src/entities/location.ts`) has no `size` or `personality` field. `region_type` exists with values {`city`, `wilderness`, `dungeon`} (a 3-element flat enum, not the 5-element settlement-size enum). `tags: string[]` carries `town` once (1 of 5 spec sizes appears tangentially as a tag, not as a typed enum). **0 of 6 spec personality traits appear as tags.** Capstone needs to add typed fields or define a tag→size/personality mapping convention.

**Honesty note 5 — `add_to_inventory` / `remove_from_inventory` are narrative-only, not merchant-enforcing.** `apps/agent/inventory_tools.py:24,105` exposes these as agent tools the DM calls after narrating a transaction ("you bought the healing potion"). They mutate `player_inventory` but do not (1) check merchant stock against `inventory_pools`, (2) check or update merchant gold pool, (3) enforce buyback limits, (4) compute the price via merchant pricing formula. The transaction flow is **narration → DB write**, not **purchase request → validate stock + gold + price → DB write**. The mechanical merchant layer is fully absent.

## Coverage matrix

Spec sections under §Merchant Inventory & Restock mapped to existing `09_economy.md` milestone items. **NEW** = spec content with no corresponding M9.x bullet.

| Spec section (file:line) | Milestone item | Notes |
| --- | --- | --- |
| Three-Tier Stock Model (merchant_inventory_restock.md:9-19) | NEW | Tier 1/2/3 classification of items by gameplay friction. Milestone 9.x does not enumerate the tier model. **Capstone should add as M9.x.** |
| Inventory Pools — 7 named pools (merchant_inventory_restock.md:23-201) | NEW | general_supplies, weapons_armor_basic, weapons_armor_quality, alchemical_supplies_common, exotic_goods, jeweler_goods, black_market. 4 shipped pools are differently-named (location/merchant-keyed). **Capstone must reconcile naming + schema.** |
| Stock Limits by Settlement (merchant_inventory_restock.md:204-234) | NEW | 5×6 size×personality matrix. Requires `Location.size` + `Location.personality` fields. **Capstone should add.** |
| Daily Restock Mechanics (merchant_inventory_restock.md:237-276) | NEW | `daily_restock_at_dawn()` + Tier 2/3 restock cadence + disruption hooks (cross-ref story-002 supply/demand events). **Capstone should add.** |
| Merchant Gold Pool (merchant_inventory_restock.md:280-337) | M9.2 — merchant pricing engine (indirect — gold pool is sale-side, pricing formula is buy-side) | 5×4 settlement×merchant-type allocations + 6 personality modifiers + buyback limits + consignment Friendly+ gate. **Capstone should add as M9.x or merge into M9.2.** |
| Special Inventory Categories (merchant_inventory_restock.md:341-376) | NEW | Traveling merchants (1-2-day visits, ±10% prices), faction-restricted inventory (cross-ref story-003 Trusted+ gating), quest-locked inventory (cross-ref content/quests.json). **Capstone should add.** |
| Voice-First Inventory Communication (merchant_inventory_restock.md:379-446) | NEW | Shop-entry narration (3-4 highlights), item-inquiry narration (4 templates), selling narration (4 templates), restock narration. **Capstone should add or fold into content/narration_templates.** |
| Implementation Reference (merchant_inventory_restock.md:449-622) | NEW | `inventory_pools` JSONB schema (tier_1_items / tier_2_items / tier_3_items with quantity_by_settlement) + `merchant_state` (current_inventory / current_gold / buyback_history / consigned_items) + `daily_restock_at_dawn` + `attempt_purchase` + `attempt_sale`. **Capstone should add.** |
| Design Decisions 87-95 (merchant_inventory_restock.md:626-646) | NEW | 9 architectural decisions. Spec L628 claims extraction to `game_mechanics_decisions.md` — **same false-extraction pattern as story-002 (96-104) and story-003 (82-86); decisions log ends at Decision 72.** Capstone bulk-fix needed. |

## Audit Status (Sprint-006) — Three-Tier Stock Model

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| Tier 1 Always-Stocked (trivial supplies — rations, torches, oil, rope, basic ammunition) | No `tier` field on `Item` (`item.ts` has `tier: 1 \| 2` but that's item-quality tier per Phase 5 audit, not the stock tier from this spec). No `tier_1_items` field on `inventory_pools` content. Shipped pool items have no tier classification at all. | None | NOT_SHIPPED |
| Tier 2 Limited Stock (depletes when sold, refills on daily restock) | Same — no tier classification. Pool items carry `quantity: N` (fixed integer, not a range), and no consumption/refill mechanism shipped. | None | NOT_SHIPPED |
| Tier 3 Unique/Rare (single instance, weekly restock OR may not restock) | No tier 3 concept. No probability check, no weekly rotation, no `restock_check: weekly` field. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Inventory Pools — Definitions

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| `inventory_pools` PostgreSQL table holds pool definitions | `scripts/migrations/001_initial_schema.sql:84-91` ships `inventory_pools (id TEXT PRIMARY KEY, data JSONB, ...)` with trigger. Table is BUILT. | None | DESIGNED↔confirmed |
| Pool drawn-from-by merchant binding (per NPC schema) | `packages/shared/src/entities/npc.ts:34` ships `inventory_pool: string \| null`. Schema BUILT. **Content NOT_SHIPPED:** 0 NPCs in `content/npcs.json` populate the field (all `null`). The 4 pools in `content/inventory_pools.json` live without merchant assignment. | None | DESIGNED |
| 7 spec-named pools (general_supplies, weapons_armor_basic, weapons_armor_quality, alchemical_supplies_common, exotic_goods, jeweler_goods, black_market) | 0 of 7 ship. 4 shipped pools are different (`market_general`, `grimjaw_weapons`, `temple_supplies`, `millhaven_supplies`) — location/merchant-keyed not type-keyed. Schema is **divergent** (see honesty note 1). | None | NOT_SHIPPED |
| Pool schema: tier_1_items + tier_2_items (with quantity_by_settlement {hamlet,village,town,city}) + tier_3_items (with presence_chance, restock_check) | Shipped pool shape is `{items: [{item_id, quantity, price}]}` — flat list, no tier split, no settlement-size quantity ranges, no presence_chance. **Divergent schema.** See honesty note 1. | None | NOT_SHIPPED |
| Tier 1 items in general_supplies (rations, waterskin, torch, oil, rope, bedroll, sack/backpack) | 0 items carry Tier 1 classification. Some matching items ship in `market_general` (rations_basic, rope_hemp, torch_bundle, waterskin) but **none in `millhaven_supplies`** (the village pool that should always carry trivial supplies per spec). | None | NOT_SHIPPED |
| Tier 2 weapons in `weapons_armor_basic` with settlement-keyed quantities (spear, dagger, handaxe, mace, short_sword, battleaxe, longsword, shortbow, light_crossbow, padded, leather, hide, shield) | 0 of 13 with spec-shape settlement-keyed quantities. `grimjaw_weapons` ships 4 weapons (longsword_guild, shortsword_basic, dagger_balanced, chain_shirt) with **flat fixed quantities** and no settlement gating. | None | NOT_SHIPPED |
| Tier 3 city-only items in `weapons_armor_quality` (Half Plate 25% chance, Plate 10% chance, masterwork variant rotation) | 0. Not present in any shipped pool. | None | NOT_SHIPPED |
| Tier 2 alchemical_supplies_common (Minor Healing Potion 1-3 town / 3-6 city; Antitoxin; Smelling salts; Common reagents) | Partial: `healing_potion` ships in 3 pools (market_general qty=5, temple_supplies qty unknown, millhaven_supplies qty unknown). `antidote_basic` ships in temple_supplies. No settlement-keyed quantity model. | None | DESIGNED |
| Black market pool with disposition-gated visibility (Friendly = some items, Trusted = full inventory) | 0 black market pool in content. No disposition-gated inventory mechanism shipped. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Stock Limits by Settlement

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| Settlement Size = 5-value enum (Hamlet, Village, Town, City, Capital) | `Location` schema has no `size` field. `region_type` ships with values {`city`, `wilderness`, `dungeon`} — 3-element flat enum that mixes settlement (city) with non-settlement (wilderness, dungeon) and **does not represent the spec's settlement-size axis**. `tags` carries `town` once (millhaven). 0 of 5 spec sizes ship as a typed enum. | None | NOT_SHIPPED |
| Size multipliers (Hamlet 0.25× tier 2 stock, Village 0.5×, Town 1.0×, City 1.5×, Capital 2.0×; Tier 3 access None/None/Limited/Yes/Yes+capital-exclusive) | No multiplier table or constant. `grep -rnE 'STOCK_MULTIPLIER\|hamlet.*0\.25\|capital.*2\.0' apps/ packages/` → 0 matches. | None | NOT_SHIPPED |
| Settlement Personality = 6-value enum (Prosperous, Struggling, Military, Trade Hub, Isolated, Cursed/Corrupted) | No `personality` field on `Location`. **0 of 6 personality traits appear in location tags.** `tags` carries `threatened`, `farming`, `quest_hub`, `corruption`, `dangerous`, etc. — adjacent narrative tags but not the spec's typed economic personality axis. | None | NOT_SHIPPED |
| Personality stock modifiers (Prosperous +25%, Struggling -50%, Military +50% weapons/-25% civilian, Trade Hub +25% all, Isolated -50% T2 + 25% price markup, Cursed -75%) | No modifier table. Honesty note 3 documents that `millhaven_supplies` content carries Isolated-like markups (+20-67% on basic supplies) by manual authoring, not by formula. | None | NOT_SHIPPED |
| Multiplicative stacking of size × personality | No stacking helper. | None | NOT_SHIPPED |
| Cursed/Corrupted: "most merchants have left or refuse to deal" | Narrative-only behavior not encoded. `content/locations.json` carries `corruption` tag on some locations but no merchant-departure mechanic. | None | NOT_SHIPPED |
| 11 row coverage: 5 sizes × 1 + 6 personality × 1 (cumulative spec rows) | Counted as 11 rows in summary; 0 ship. | None | NOT_SHIPPED |
| 5 size × Tier 3 access (None/None/Limited/Yes/Yes+exclusive) | Tier 3 concept itself is NOT_SHIPPED (above). | None | NOT_SHIPPED |
| 6 personality × inventory modifier | Above. | None | NOT_SHIPPED |
| Tier 1 pool access by settlement (Hamlet=Limited, Village+=Yes) | No tier access gating. | None | NOT_SHIPPED |
| Settlement personality × gold pool (parallel modifier set) | See Gold Pool section below. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Daily Restock Mechanics

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| Inventory restocks once per in-game day at dawn (06:00 in-game) | `content/inventory_pools.json` pools carry `restock_interval_hours: 24` — the **intent** to restock daily is recorded as data, but **no consumer reads this field**. `grep -rnE 'restock_interval_hours\|daily_restock\|restock_at_dawn' apps/ packages/` → 0 matches. Field BUILT in content, mechanism NOT_SHIPPED. | None | DESIGNED |
| Restock process: per-merchant per-tier roll against quantity range, gold pool reset, buyback history reset, consignment expiration check | `daily_restock_at_dawn()` function does not exist. No simulation tick layer in `apps/agent/` invokes inventory refresh. | None | NOT_SHIPPED |
| Restock frequency by tier (Tier 1 continuous, Tier 2 daily, Tier 3 daily probability OR weekly rotation) | Tier model NOT_SHIPPED (above). | None | NOT_SHIPPED |
| Restock disruption hooks (trade route disrupted -50% T2, festival +50%, faction control change, player intervention) | Cross-ref story-002: supply/demand engine entirely NOT_SHIPPED; restock disruption inherits. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Merchant Gold Pool

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| Daily gold allocation table (Hamlet 10sp/Village 25-50sp/Town 75-200sp/City 200-600sp/Capital 500-1500sp across 4 merchant types) | 0 of 5×4=20 entries ship. No `merchant_gold_pool` constants. `grep -rnE 'current_gold\|merchant_gold\|gold_pool\|max_gold' apps/ packages/` → 0 matches. | None | NOT_SHIPPED |
| `merchant_state.current_gold` + `merchant_state.max_gold` tracked daily | No `merchant_state` table or Redis cache. The spec-defined shape (`merchant_id, current_inventory, current_gold, max_gold, last_restock_tick, buyback_history, consigned_items`) is absent. | None | NOT_SHIPPED |
| 3-option mechanic on player-sells-item-exceeding-pool (partial purchase, refusal, consignment) | None of the 3 mechanisms ship. The `add_to_inventory`/`remove_from_inventory` agent tools (`inventory_tools.py:24,105`) handle the DB mutation side of a narrative transaction but have no concept of merchant gold balance. | None | NOT_SHIPPED |
| Consignment at Friendly+ (deferred payment, 1d4 days, 10% commission, expiration handling) | No consignment table, no expiration ticker. | None | NOT_SHIPPED |
| Gold pool empty → merchant refuses purchases until restock (still can sell) | Not enforced anywhere. | None | NOT_SHIPPED |
| 6 personality modifiers on gold pool (Prosperous +50%, Struggling -50%, Military +100% weapons-specific, Trade Hub +25%, Isolated -25%, Cursed -75%) | 0 of 6 (parallel to inventory modifiers above). | None | NOT_SHIPPED |
| Buyback limits (Common weapons 3/day, Common consumables 5/day, Quality 2/day, Unique 1/day; beyond limit = 50% price) | No `buyback_history` per merchant. No daily reset. No per-item-type limit table. | None | NOT_SHIPPED |
| Buyback-limit narration ("I've already taken three short swords off you this week") | No template. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Special Inventory Categories

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| Traveling merchants (1-week visit frequency, 1-2 day stay, +10% buy / -10% sell, 1-2 higher-tier items + 1 rumor item) | No traveling-merchant entity type. `content/npcs.json` merchants are static-location only. No itinerary ticker. | None | NOT_SHIPPED |
| Faction-restricted inventory (Thornwatch / Keldaran / Ashmark gated by min faction tier) | Cross-ref story-003: faction reputation pricing pipeline NOT_SHIPPED end-to-end; faction-restricted inventory inherits. `Item.value_modifiers` carries faction-keyed overlays (BUILT per story-001) but **does not gate access** to the item. | None | DESIGNED |
| Quest-locked inventory (item visible only when quest condition met) | `content/quests.json` ships quest data (story-001 BUILT finding) but no merchant-side quest-condition gate. No `item.requires_quest_state` field on Item interface. | None | NOT_SHIPPED |
| Faction merchants hold restricted items in reserve (not in standard rolls) | Mechanism doesn't exist. | None | NOT_SHIPPED |
| Quest-condition visibility check at purchase time | Not encoded. | None | NOT_SHIPPED |
| "Rotating feature item" per traveling merchant (Drathian blade, Keldaran tool, Aelindran star-chart) | No rotating-feature-item registry. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Voice-First Inventory Communication

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| Shop-entry narration (3-4 highlights, never full inventory listing) | No template, no system-prompt fragment. `grep -rnE 'shop_entry_narration\|shop_overview\|inventory_highlight' apps/agent/` → 0 matches. | None | NOT_SHIPPED |
| Specific-item-inquiry narration (4 sub-templates: available / out-of-stock / wrong-location / faction-restricted) | No templates. | None | NOT_SHIPPED |
| Selling narration (4 templates: within-pool / beyond-pool / buyback-limit / refusal) | No templates. | None | NOT_SHIPPED |
| Restock narration ("Fresh stock is coming in — caravans arrived overnight") | No template. No restock event surfacing to DM. | None | NOT_SHIPPED |
| Anti-pattern guards (no exhaustive listing, no unprompted prices, no mechanical language, no inventory state dumps) | The DM is prompted via system-prompt scaffolding (per Phase 1 audit); no specific anti-pattern guard for merchant interactions ships. | None | NOT_SHIPPED |
| Tier-aware highlight rule (mention Tier 2 by name, summarize Tier 1 as "the usual supplies", prominently highlight Tier 3) | Tier model NOT_SHIPPED (above) so this rule has no domain. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Implementation Reference

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| `inventory_pools` JSONB schema (tier_1_items + tier_2_items + tier_3_items shape per spec L453-480) | Table BUILT (above). **Content schema diverges** (honesty note 1). | None | DESIGNED |
| `merchant_state` (Redis with PostgreSQL backing) — current_inventory / current_gold / max_gold / last_restock_tick / buyback_history / consigned_items | No `merchant_state` table in `scripts/migrations/`. No Redis key pattern. Spec assumes Bun.redis (architectural baseline); specific contract not encoded. | None | NOT_SHIPPED |
| `daily_restock_at_dawn()` simulation tick callback | Function does not exist. No simulation tick infrastructure in apps/agent (training cycle has `async_rules.py` per Phase 6 audit; no economy tick). | None | NOT_SHIPPED |
| `attempt_purchase(player_id, merchant_id, item_id, quantity)` — checks stock → calculates price → checks player gold → checks capacity → executes transaction | Function does not exist. Shipped path: DM narrates → calls `add_to_inventory` (narrative-only, see honesty note 5). | None | NOT_SHIPPED |
| `attempt_sale(player_id, merchant_id, item_id, quantity)` — calculates 50%-of-value offer → checks buyback limit → checks merchant gold → executes | Function does not exist. Shipped path: DM narrates → calls `remove_from_inventory`. | None | NOT_SHIPPED |
| `apply_pricing_modifiers(base_price, player_id, merchant) → price` | Cross-ref story-001 + story-002 + story-003: all pricing-modifier functions NOT_SHIPPED. | None | NOT_SHIPPED |
| `add_to_inventory` / `remove_from_inventory` agent tools (narrative path) | `apps/agent/inventory_tools.py:24,105` BUILT. Player-side inventory mutation works end-to-end; merchant-side enforcement absent (honesty note 5). | `apps/agent/tests/test_db.py:513` (insert assertion) | BUILT |

## Audit Status (Sprint-006) — Design Decisions 87-95

Spec L626-646 records 9 architectural decisions. Spec L628 claims "Extracted to `game_mechanics_decisions.md` for canonical reference" — **same false-extraction pattern as story-002 (96-104) and story-003 (82-86)**. The canonical decisions log terminates at Decision 72 (Economy Reconciliation). Decisions 87-95 are still spec-local. None are encoded.

| Decision | Item (verbatim) | Status |
| --- | --- | --- |
| 87 | Three-tier stock model balances frictionless basics with meaningful scarcity | NOT_SHIPPED (no tier model) |
| 88 | Restock cadence is once per in-game day at dawn | NOT_SHIPPED (no restock tick) |
| 89 | Merchant gold pools are finite and scale with settlement size | NOT_SHIPPED (no gold pool tracking) |
| 90 | Merchant gold pools restock daily at dawn, parallel to inventory | NOT_SHIPPED (no daily restock) |
| 91 | Buyback limits prevent farming exploits | NOT_SHIPPED (no buyback tracking) |
| 92 | Always-stocked items limited to truly trivial supplies | NOT_SHIPPED (no Tier 1 classification) |
| 93 | Consignment is a Friendly+ relationship feature | NOT_SHIPPED (no consignment) |
| 94 | Shop entry narration uses 3-4 highlights, not full inventory | NOT_SHIPPED (no narration templates) |
| 95 | Settlement personality stacks multiplicatively on size | NOT_SHIPPED (neither dimension typed; neither modifier shipped) |

## Deliverables status (per 09_economy.md M9.2 §Deliverables, cross-doc)

This audit story is doc-only and does not own M9.x deliverables directly — the capstone (story-008) will. Mapping for the capstone:

- `inventory_pools` table: **DESIGNED↔confirmed** (table BUILT; content schema diverges from spec)
- 7 spec-named pools (general_supplies + 6 specialist pools): **NOT_SHIPPED** (4 shipped are differently-keyed)
- Three-tier stock model (Tier 1/2/3): **NOT_SHIPPED**
- Per-pool settlement-keyed quantity ranges: **NOT_SHIPPED**
- `merchant_state` (current_inventory + current_gold + buyback_history + consigned_items): **NOT_SHIPPED**
- `daily_restock_at_dawn` simulation tick: **NOT_SHIPPED**
- `attempt_purchase` / `attempt_sale` enforcing functions: **NOT_SHIPPED**
- `Location.size` + `Location.personality` fields: **NOT_SHIPPED**
- 5×6 size×personality stock + gold modifier tables: **NOT_SHIPPED**
- Buyback limits (3/5/2/1 per type): **NOT_SHIPPED**
- Consignment system (Friendly+ deferred payment): **NOT_SHIPPED**
- Traveling merchants (1-week itinerary, ±10% pricing, rumor items): **NOT_SHIPPED**
- Faction-restricted inventory + Quest-locked inventory: **DESIGNED↔aspirational** (faction-modifier overlay BUILT on items per story-001; gate enforcement absent)
- DM narration templates (6 patterns): **NOT_SHIPPED**
- 9 design decisions 87-95 encoded as constants: **NOT_SHIPPED**

## Out-of-scope findings (Sprint-spec-cleanup punch list)

Routed to `audit/README.md` Sprint-006 section by capstone (story-008) per wisdom `d0715b09a1df`:

1. **`inventory_pools` schema choice.** Capstone must pick between (a) restructuring content to spec shape (tier_1/2/3_items + quantity_by_settlement) and adding NPC.inventory_pool population, (b) updating spec to match shipped flat-per-merchant model and merging the per-merchant pool into NPC schema, or (c) introducing an adapter layer. Recommend (a) — spec model scales to settlement-size-aware quantity; current model bakes settlement-size into per-merchant authoring effort.
2. **Pool prices vs Item.value_base.** Pool entries carry `price` and items carry `value_base`; for `market_general` and `grimjaw_weapons` they match exactly, but `temple_supplies` (-10%) and `millhaven_supplies` (+20-67%) diverge in ways that look like manual personality-modeling (Isolated +25% spec rule, approximately). Capstone must decide: delete pool.price and compute from value_base via formula, OR keep pool.price as a per-merchant override with spec-compliant semantics (rename to `base_price_override`).
3. **`Location` schema needs `size: enum(hamlet|village|town|city|capital)` + `personality: enum[]`** for the spec's 5×6 stock/gold parameter matrix to have a domain. Current `region_type` (3-value flat enum) conflates settlement-and-non-settlement and lacks the size axis.
4. **Tier classification on items** (Tier 1 always-stocked vs Tier 2 limited vs Tier 3 unique) — needed on `Item` or on pool entries. Spec's narration rules (3-4 highlights) depend on this classification.
5. **NPC merchant→pool binding is BUILT on schema but unused.** 0 of 14 NPCs in `content/npcs.json` populate `inventory_pool` field. Capstone should backfill once role archetypes (M6.1) land or accept this as a content-side task to be sequenced after Phase 6 mentor/merchant typing.
6. **Decisions 87-95 are NOT extracted to `game_mechanics_decisions.md`** despite spec L628 claiming they are. This is the **third audit story to find the same false-extraction pattern** (story-002 found it for 96-104, story-003 for 82-86). Capstone should bulk-fix all three ranges + identify gaps (73-81, 87-95, 96-104 imply Decisions 73-81 are also undocumented in the log).
7. **Pool naming conflict.** Spec uses **type-based pool names** (general_supplies / weapons_armor_basic / ...); content uses **location/merchant-based names** (market_general / grimjaw_weapons / temple_supplies / millhaven_supplies). The two models are different design intents (reusable type-pool vs per-merchant authoring). Capstone needs explicit decision and content migration plan if switching to spec model.
8. **Narrative-only `add_to_inventory` / `remove_from_inventory` tools.** Spec's `attempt_purchase` / `attempt_sale` are *replacements* for these (with stock/gold/buyback enforcement), not additions. Capstone should clarify whether new tools wrap or supersede; backwards-compatibility with narrative-only paths matters for the DM's existing prompts.
9. **`restock_interval_hours: 24` field on shipped pools is dormant.** No consumer. When daily_restock_at_dawn lands, decide whether this per-pool override (vs the spec's globally-daily cadence) is intentional configuration or unused metadata.

## Verification

Verified-at: 4046efc4fc19d9c9c8db80a83b0d0a495f7bb012

Grep commands used (all from repo root; 0 matches unless noted):

```bash
# Merchant state machine
grep -rnE 'merchant_state|current_gold|merchant_gold|gold_pool|max_gold' apps/ packages/

# Daily restock + tier model
grep -rnE 'daily_restock|restock_at_dawn|restock_interval_hours|tier_1_items|tier_2_items|tier_3_items' apps/ packages/

# Purchase / sale enforcing functions
grep -rnE 'def.*attempt_purchase|def.*attempt_sale|def.*apply_pricing|buyback_history|buyback_limit' apps/agent/

# Settlement size + personality
grep -rnE 'settlement_size|hamlet|capital|STOCK_MULTIPLIER|prosperous|struggling|cursed_corrupted|trade_hub|isolated' apps/ packages/

# Traveling merchant + consignment + quest-lock
grep -rnE 'traveling_merchant|consigned_item|consignment|requires_quest_state' apps/ packages/

# Narration templates
grep -rnE 'shop_entry_narration|shop_overview|inventory_highlight|restock_narration' apps/agent/

# Confirmed-present substrate (returned matches):
grep -n 'CREATE TABLE inventory_pools' scripts/migrations/001_initial_schema.sql      # L84
grep -n 'inventory_pool' packages/shared/src/entities/npc.ts                           # L34
grep -n 'add_to_inventory\|remove_from_inventory' apps/agent/inventory_tools.py        # L24, L105
grep -n 'player_inventory' apps/agent/db_queries.py apps/agent/db_mutations.py         # 4 sites

# Pool / NPC binding probe
python3 -c "import json; d=json.load(open('content/npcs.json')); npcs=d['npcs'] if isinstance(d,dict) else d; print('npcs with inventory_pool populated:', sum(1 for n in npcs if n.get('inventory_pool')))"
# Result: 0

# Pool / item price co-authoring sample
python3 -c "import json; items={i['id']: i.get('value_base') for i in json.load(open('content/items.json'))}; pools = json.load(open('content/inventory_pools.json')); pools = pools if isinstance(pools,list) else pools.get('pools', list(pools.values())); [print(p['id'], '→', [(it['item_id'], it.get('price'), items.get(it['item_id'])) for it in p.get('items',[])[:4]]) for p in pools]"
# market_general & grimjaw_weapons → exact match; temple_supplies → -10% on healing_potion; millhaven_supplies → +20-67% markups

# Location size/personality probe
python3 -c "import json; locs = json.load(open('content/locations.json')); locs = locs['locations'] if isinstance(locs,dict) else locs; print('region_type values:', set(l.get('region_type','?') for l in locs)); tags=set(); [tags.update(l.get('tags',[])) for l in locs]; spec_sizes={'hamlet','village','town','city','capital'}; spec_personality={'prosperous','struggling','military','trade_hub','isolated','cursed','corrupted'}; print('spec sizes in tags:', spec_sizes & tags); print('spec personality in tags:', spec_personality & tags)"
# region_type: {'city', 'wilderness', 'dungeon'}; sizes: {'town'} (1/5); personality: {} (0/6)
```
