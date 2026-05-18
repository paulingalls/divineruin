# Phase 9 Audit — Economy / Gold Sink Ledger (Sprint-006 story-005)

Sprint-006 / Milestone 6 (story-005). Read-only audit of `docs/game_mechanics/economy/gold_sink_ledger.md` (428 lines, 1 H2 with 7 major subsections covering 8 sink categories, 5 gap-proposals, and 9 design decisions) against shipped code in `apps/agent/`, `apps/server/src/`, `packages/shared/src/entities/`, `content/`, and `scripts/migrations/`. Status legend (matches sprint-004 audit/README.md L49-58): **BUILT** = code present and matches spec; **DESIGNED** = spec well-defined and partial code exists, but the symbol/feature is missing, renamed, or diverges; **NOT_SHIPPED** = no implementation found. Sibling sprint-006 audit files: `phase-9-economy.md` (story-001), `phase-9-supply-demand.md` (story-002), `phase-9-faction-pricing.md` (story-003), `phase-9-restock.md` (story-004).

Verified-at: 7ca287c3ab1cbd4a30619b6e42b79cb002704fe2

## Summary

| Section | BUILT | DESIGNED | NOT_SHIPPED |
| --- | --- | --- | --- |
| Categorization Framework (8 sink categories) | 0 | 0 | 8 |
| Maintenance Sinks (item repair + companion gear) | 0 | 0 | 2 |
| Subsistence Sinks (lodging + food + traveling merchant premium) | 0 | 1 | 4 |
| Combat Sinks (consumables + death/resurrection magic) | 0 | 2 | 6 |
| Progression Sinks (mentor fees + faction donations + bounty materials) | 0 | 0 | 3 |
| Crafting Sinks (commissions + workspace rental + materials) | 0 | 0 | 3 |
| Service Sinks (5 NPC services) | 0 | 0 | 5 |
| Lifestyle Sinks (luxury + NPC gifts + tavern entertainment) | 0 | 0 | 3 |
| Endgame Sinks (legendary repair + resurrection + faction investments + letter of credit + consignment + warehouse) | 0 | 0 | 6 |
| Magnitude Analysis (faucet/sink balance check) | 0 | 0 | 1 |
| Gap Analysis (5 proposed additions: companion gear, bribery, travel tolls, property, NPC gifts) | 0 | 0 | 5 |
| Implementation Notes (sink event logging) | 0 | 0 | 2 |
| Design Decisions 105-113 (9 decisions) | 0 | 0 | 9 |

**Headline finding:** Gold sink ledger is **almost entirely NOT_SHIPPED**, but this is largely a **cross-reference confirmation audit**: gold_sink_ledger.md is explicitly a *consolidation* document (spec L3) — every sink it catalogs is sourced from another spec, and most of those sources were already audited as NOT_SHIPPED in sprint-003/004/005/006-prior. What ships across the entire ledger: (1) `player.gold: int` field, set once at character creation (`apps/agent/creation_rules.py:257` writes `"gold": cls.starting_gold`) and **never mutated** by any code — `grep -rnE 'gold.*-=|gold.*\+=' apps/agent/` → 0 matches; (2) 6 consumable items in `content/items.json` (healing_potion, antidote_basic, holy_water, rations_basic, millhaven_provisions, restoration_salve) with typed `effects[]` arrays — items exist but **no `consume_item` function fires a gold-removal hook** when one is used; (3) `apps/agent/rest_mechanics.py` ships `apply_short_rest`/`apply_long_rest`/`apply_rest` — rest itself is BUILT as pure functions (stamina/focus/HP restoration) — but **lodging-cost gating is absent** (rest is free regardless of location, no `pay_for_room(quality)` surface); (4) innkeeper NPC (`content/npcs.json:263` `innkeeper_maren`) exists as a narrative entity, not a service-pricing surface; (5) quest reward processing ships at `apps/agent/quest_tools.py:138-167` per story-001 (faucet side only). **What does NOT ship**: zero sink_event log table, zero `sink_category` enum, zero magnitude-analysis telemetry, zero of 5 gap-analysis additions (bribery, tolls, property, companion gear, NPC gifts), zero of 9 design decisions 105-113 encoded, zero of 8 sink categories as code constants. The 31+ punch-list items already routed to capstone by stories 001-004 cover most of this surface; this audit's contribution is the **categorization framework** and the **sink event logging infrastructure**, both NEW work.

**Honesty note 1 — gold_sink_ledger.md is a consolidation doc, not new mechanics.** Spec L3 explicitly says: "This is primarily a *consolidation* document — most sinks already exist mechanically across other files. The ledger view exists to verify economic balance, identify gaps, and provide a canonical reference for inflation control." This means most rows in the ledger are **cross-references to prior subsystems already audited**. Per-sink-row NOT_SHIPPED findings inherit from: Phase 5 durability/repair (audit phase-5-durability.md → NOT_SHIPPED), Phase 6 mentor fees (audit phase-6-mentors.md → DESIGNED), faction donations (audit phase-9-faction-pricing.md → NOT_SHIPPED), consignment + traveling merchant premium (audit phase-9-restock.md → NOT_SHIPPED), workspace rental + crafting commissions + NPC services (audit phase-9-economy.md → NOT_SHIPPED). The unique-to-this-doc contributions are the **categorization framework** (8 sink categories), the **sink event logging schema** (spec L389-402), the **magnitude analysis** (telemetry/balance system), and the **5 gap-analysis additions** (bribery, tolls, property, companion gear, NPC gifts).

**Honesty note 2 — `player.gold` is a one-write, no-read field.** `apps/agent/creation_rules.py:257` writes `"gold": cls.starting_gold` into the player JSONB at character creation. **No code reads, increments, or decrements the value.** `grep -rnE "['\"]?gold['\"]?:\s*[0-9]" apps/agent/ apps/server/src/` returns only the literal `gold:47` in `apps/server/src/debug.ts:182` (a debug-page mock payload), plus 18 `starting_gold=N` definitions in `creation_classes.py`. The mutation surface — where consume_potion debits 25 sp, where sell_to_merchant credits, where pay_mentor debits — does not exist. **Player wealth is effectively immutable after creation**: the field exists, the integer ships, but the spec's faucet/sink dynamic has no code path.

**Honesty note 3 — `rest_mechanics.py` is BUILT but lodging-cost-gating is NOT_SHIPPED.** `apps/agent/rest_mechanics.py` (3 pure functions: `apply_short_rest`, `apply_long_rest`, `apply_rest`) handles stamina/focus/HP restoration on rest. This is per gm_core / Phase 1 audit territory and confirmed BUILT. But the spec's **lodging-cost sink** (Common Room 1 sp, Private 5 sp, Fine 15 sp — gold_sink_ledger.md:94-99) requires gating rest behind a payment + quality-modifier check. **Zero of the 3 lodging tiers ship as cost gates.** The rest functions take no `lodging_quality` parameter, no cost is debited, no quality modifier is applied. A player can long-rest anywhere — outdoors, in a tavern, in a dungeon — for free. **Subsistence sink is structurally NOT_SHIPPED despite rest itself being BUILT.**

**Honesty note 4 — Quest rewards as faucet ARE built; sink side is not.** Per story-001 audit: `apps/agent/quest_tools.py:138-167` processes quest rewards (xp_reward, item rewards). The faucet half of the economy works. The sink half (consumable use, repair, services, donations, lodging) does not. **Faucet/sink balance check from spec L310 is unverifiable** because only one side has telemetry. Magnitude analysis section of spec is entirely aspirational — no sink_event_log table exists to aggregate per-category drain.

**Honesty note 5 — Fourth sprint-006 audit story to find the false-extraction pattern for decisions.** Spec L410 claims decisions 105-113 are "Extracted to `game_mechanics_decisions.md` for canonical reference." **They are not** — the canonical decisions log terminates at Decision 72 (Economy Reconciliation). Same pattern as story-002 found for 96-104, story-003 for 82-86, story-004 for 87-95. The combined implied undocumented range is now 73-81 + 87-95 + 96-104 + 105-113 = **at least 35 design decisions** that exist as spec-local text but are not extracted to the canonical log. Capstone bulk-fix is overdue.

## Coverage matrix

Spec sections under §Gold Sink Ledger mapped to existing `09_economy.md` milestone items. **NEW** = spec content with no corresponding M9.x bullet. Most rows route to prior audit files since this is a consolidation doc.

| Spec section (file:line) | Milestone item | Notes / cross-ref |
| --- | --- | --- |
| Design Philosophy — 4 good-sink properties + 5 bad-sink anti-patterns (gold_sink_ledger.md:9-33) | NEW | Design rubric for sinks. **Capstone should add as M9.x preamble.** |
| Categorization Framework — 8 sink categories (gold_sink_ledger.md:37-61) | NEW | (Maintenance / Subsistence / Combat / Progression / Crafting / Service / Lifestyle / Endgame). **Capstone should add.** |
| Item Repair sink (gold_sink_ledger.md:67-83) | M9.1 — repair pricing | Cross-ref `phase-5-durability.md`: durability mechanics NOT_SHIPPED; cross-ref `phase-9-economy.md` story-001 audit: 4 repair-tier pricing NOT_SHIPPED. Inheritance: full NOT_SHIPPED. |
| Companion Equipment Wear sink (gold_sink_ledger.md:85-87) | NEW (spec gap, Decision 112 proposal) | Companion gear at half player cost. No `CompanionEquipment` schema or repair hook. NOT_SHIPPED. |
| Lodging sink (gold_sink_ledger.md:90-103) | NEW | 3-tier lodging cost (Common 1sp / Private 5sp / Fine 15sp) gating rest quality. See honesty note 3. **DESIGNED** at the rest-mechanic substrate; **NOT_SHIPPED** for cost gating. |
| Food/Rations sink (gold_sink_ledger.md:104-115) | M9.1 — Food & Lodging price table | Cross-ref `phase-9-economy.md` story-001: food/lodging price-table NOT_SHIPPED. `rations_basic` ships as a content item; no consumption-per-day mechanic. |
| Traveling Merchant Premium (gold_sink_ledger.md:117-121) | Cross-ref story-004 (phase-9-restock.md) | Traveling-merchant entity-type NOT_SHIPPED per story-004. Inheritance: NOT_SHIPPED. |
| Consumables Used in Combat (gold_sink_ledger.md:125-138) | M9.1 — consumables pricing (cross-ref) | 6 consumable items ship in `content/items.json`; no `consume_item` hook fires gold-removal. **DESIGNED** at the content layer; **NOT_SHIPPED** for the sink event. |
| Death and Resurrection magic (gold_sink_ledger.md:140-157) | Cross-ref story-001 (phase-9-economy.md) NPC Services | 8 spec services (Revivify, Resurrection, Greater Restoration, Dispel Corruption, Cure Poison, Heal Wounds, Remove Curse, Identify-Hollow). All NOT_SHIPPED per story-001. Spec note: Mortaen's escalating costs are *non-monetary* — only spell components + NPC service fees are gold sinks (preserved as Decision 107). |
| Mentor Training Fees (gold_sink_ledger.md:162-173) | Cross-ref story-001 + Phase 6 (phase-6-mentors.md) | 5 fee bands NOT_SHIPPED per story-001. Phase 6 mentor registry NOT_SHIPPED. Compound dep. |
| Faction Donations (gold_sink_ledger.md:175-179) | Cross-ref story-003 (phase-9-faction-pricing.md) | +1 reputation per 25 sp donated NOT_SHIPPED per story-003. Inheritance: NOT_SHIPPED. |
| Faction Bounty Materials (gold_sink_ledger.md:181-185) | Cross-ref story-003 + quests | Bounty-quest subtype not in `content/quests.json` schema per story-003. Inheritance: NOT_SHIPPED. |
| Crafting Commissions (gold_sink_ledger.md:189-199) | Cross-ref story-001 | 3-tier commission pricing NOT_SHIPPED per story-001. |
| Workspace Rental (gold_sink_ledger.md:201-214) | Cross-ref story-001 + Phase 5 | 4 workspace rates + disposition discount NOT_SHIPPED per story-001 + `phase-5-recipes-resolution.md`. |
| Crafting Materials sink (gold_sink_ledger.md:216-220) | NEW | Buying reagents from merchants. Cross-ref story-002 (Item.value_modifiers exists but no purchase-sink hook). NOT_SHIPPED. |
| Service Sinks — 5 NPC services (gold_sink_ledger.md:222-236) | Cross-ref story-001 | (Identify item, Identify Hollow material, Research common, Research obscure, Translate text). All NOT_SHIPPED per story-001. |
| Luxury Goods (gold_sink_ledger.md:240-254) | Cross-ref story-001 (Jeweler / Exotic Goods pools) + story-004 | Spec mentions Jeweler + Exotic Goods pools — those pools are NOT_SHIPPED in `content/inventory_pools.json` per story-004. Inheritance: NOT_SHIPPED. |
| NPC Gifts (gold_sink_ledger.md:256-258) | NEW (spec gap, Decision proposal) | `appreciated_gifts` field on NPC + disposition-shift mechanic. **No `appreciated_gifts` field on `Npc` schema** (`grep -nE 'appreciated_gifts' packages/shared/src/entities/npc.ts` → 0). NOT_SHIPPED. |
| Tavern Entertainment (gold_sink_ledger.md:260-264) | NEW | Buying rounds, hiring bards, gambling. NOT_SHIPPED. |
| Endgame Sinks — Legendary Repair, Resurrection, Faction Investments, Letter of Credit, Consignment, Warehouse Storage (gold_sink_ledger.md:266-291) | Cross-refs to stories 001/003/004 | All 6 endgame sinks inherit NOT_SHIPPED from their source audits. |
| Magnitude Analysis — telemetry table + faucet/sink balance check (gold_sink_ledger.md:296-310) | NEW | Per-session drain estimates by category + balance equation. No telemetry surface. NOT_SHIPPED. |
| Gap 1: Companion Equipment Maintenance (gold_sink_ledger.md:318-324) | NEW | Capstone-routed proposal. |
| Gap 2: Bribery System (gold_sink_ledger.md:326-338) | NEW | Capstone-routed proposal. |
| Gap 3: Travel Tolls (gold_sink_ledger.md:340-352) | NEW | Capstone-routed proposal (with free-alternative constraint per Decision 110). |
| Gap 4: Property and Housing (gold_sink_ledger.md:354-364) | NEW (Phase 2+) | Spec explicitly defers to Phase 2+ multiplayer. |
| Gap 5: NPC Gift System (gold_sink_ledger.md:366-374) | NEW | Capstone-routed proposal. |
| Implementation — Sink Event Logging schema (gold_sink_ledger.md:389-402) | NEW | New event type `sink_event` with player_id / sink_category / sink_type / item_id / amount_sp / context / timestamp. Required for inflation analysis per cross-ref to inflation_targets_controls.md (story-006). **Capstone should add.** |
| Design Decisions 105-113 (gold_sink_ledger.md:408-428) | NEW | 9 decisions. Spec L410 false-extraction claim — see honesty note 5. |

## Audit Status (Sprint-006) — Categorization Framework

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| 8 sink categories (Maintenance / Subsistence / Combat / Progression / Crafting / Service / Lifestyle / Endgame) with distinct design intents | No `SinkCategory` enum or constant. `grep -rnE 'SinkCategory|sink_category|SINK_CATEGORIES' apps/ packages/` → 0 matches. The categorization is documentation-only; no code surface organizes sinks by category. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Maintenance Sinks

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| Item repair pricing by tier (Common 2sp / Uncommon 10sp / Rare 50sp / Legendary 200+sp) every 5-10 combats | Cross-ref `phase-5-durability.md` Sprint-004 audit: durability mechanics NOT_SHIPPED end-to-end. No repair function, no degradation tracking, no per-tier repair-cost table. | None | NOT_SHIPPED |
| Companion equipment wear at half player gear cost | Spec gap (gap-1 proposal). No CompanionEquipment schema or degradation hook. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Subsistence Sinks

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| Rest infrastructure (short rest, long rest) | `apps/agent/rest_mechanics.py:8-32` ships `apply_short_rest`, `apply_long_rest`, `apply_rest` as pure functions handling stamina/focus/HP restoration. BUILT for the rest-mechanic itself. | (rest mechanics likely tested by Phase 1 — not re-verified in this audit) | BUILT (substrate; out-of-scope for this story) |
| Lodging cost-gating (Common Room 1sp / Private 5sp / Fine 15sp + quality modifier on rest) | No `lodging_quality` parameter on `apply_rest`. No cost debit on rest. No `pay_for_room(quality, gold)` surface. Innkeeper NPC (`content/npcs.json:263` `innkeeper_maren`) exists as narrative entity, not pricing surface. | None | NOT_SHIPPED |
| Rations / food consumption (5cp/day rations + tavern meals 1-2sp + tavern drinks 1-5cp + fresh food 1sp/day) | `content/items.json` ships `rations_basic` (value_base=5, type=consumable). No per-day consumption mechanic; no tavern-meal item; no spoilage tracker; no fresh-food-spoilage clock. | None | NOT_SHIPPED |
| Traveling merchant +10% premium | Cross-ref story-004 audit: traveling-merchant entity NOT_SHIPPED. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Combat Sinks

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| 6 named combat consumables (Minor Healing Potion 25sp, Antitoxin 15sp, Smelling Salts 5sp, Anti-Hollow Oil 10sp, Greater Healing Potion 75sp, Crossbow bolts 5sp) | Of 6 spec consumables, **3 ship as items** in `content/items.json`: `healing_potion` (effects: heal 2d4+2), `antidote_basic` (cure_poison), `holy_water` (thrown radiant 2d6 vs hollow — adjacent to Anti-Hollow Oil). Smelling Salts, Greater Healing Potion, Crossbow bolts: not in content. Item content layer is DESIGNED. | None | DESIGNED |
| Consume-item gold-removal hook | No `consume_item` function. `grep -rnE 'def.*consume_item|on_consume|item_consumed' apps/agent/` → 0 matches. Items ship with `effects[]` arrays but no consumption pipeline mutates `player.gold` or `player_inventory`. | None | NOT_SHIPPED |
| Revivify diamond (50 gc = 500 sp component) | No spell component pricing. No `revivify` spell or diamond requirement in code. | None | NOT_SHIPPED |
| Resurrection diamond (500 gc = 5,000 sp) | Same — no spell mechanic, no diamond requirement. | None | NOT_SHIPPED |
| 5 NPC death-recovery services (Resurrection 1000+sp, Greater Restoration 200sp, Dispel Corruption 25sp, Cure Poison 15sp, Heal Wounds 5sp, Remove Curse 50sp) | Cross-ref story-001 NPC Services audit: all 11 NPC services NOT_SHIPPED. | None | NOT_SHIPPED |
| Mortaen's death system: attribute loss + item loss + memory fragments (non-monetary, per Decision 107) | God-of-death narrative system not in `content/gods.json` shape (per Phase 6 audit — gods schema BUILT, mechanical layer for divine consequence NOT_SHIPPED). | None | NOT_SHIPPED |
| Player agency: divine archetypes self-heal/self-resurrect | Cleric/Paladin/Oracle archetypes exist in `apps/agent/creation_classes.py` (BUILT) but self-resurrection ability NOT_SHIPPED. | None | DESIGNED |
| Items consumed in combat decrement inventory | `remove_from_inventory` agent tool ships (`apps/agent/inventory_tools.py:105`) per story-004 audit. Item-quantity decrement BUILT at the narrative path; no automatic-on-consume trigger. | (DM narrates → tool fires) | DESIGNED |

## Audit Status (Sprint-006) — Progression Sinks

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| 5 mentor fee bands (15-20sp informal / 25-40sp standard / 50-75sp elite / 80-100sp legendary / 0sp honor-based) | Cross-ref story-001 + `phase-6-mentors.md`: mentor registry NOT_SHIPPED; fee structure inherits NOT_SHIPPED (training-cycle state machine BUILT, fee charging NOT_SHIPPED). | None | NOT_SHIPPED |
| Faction donations (+1 rep per 25sp, cap +3/week, Trusted-tier max) | Cross-ref story-003: faction reputation pipeline NOT_SHIPPED. Inheritance. | None | NOT_SHIPPED |
| Faction bounty material costs (variable) | Cross-ref story-003: bounty quest subtype NOT_SHIPPED. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Crafting Sinks

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| 3-tier crafting commission pricing (T1 5/15sp, T2 25/75sp, T3 100/300+sp) | Cross-ref story-001: NOT_SHIPPED. | None | NOT_SHIPPED |
| 4 workspace rental rates (Workshop 2sp/Forge 5sp/Lab 10sp/F+L 12sp) + disposition discount (Friendly 80%, Trusted 60%, Standing access free) | Cross-ref story-001 + `phase-5-recipes-resolution.md`: NOT_SHIPPED. | None | NOT_SHIPPED |
| Crafting materials sink (buying reagents from merchants) | Cross-ref story-002 + story-004: purchase-side sink hook NOT_SHIPPED. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Service Sinks

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| Identify item (10sp), Identify Hollow material (25sp), Research common (15sp), Research obscure (50sp), Translate text (25sp) | Cross-ref story-001 NPC Services: all 5 NOT_SHIPPED. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Lifestyle Sinks

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| Luxury goods (5 price bands: common gem 10-25sp, quality gem 50-100sp, rare gem 200+sp, jewelry 25-150sp, exotic 30-200sp) | Cross-ref story-004 Jeweler + Exotic Goods inventory pools: NOT_SHIPPED (4 shipped pools don't include these). | None | NOT_SHIPPED |
| NPC gifts (disposition lubrication) — `appreciated_gifts` field on NPC | No `appreciated_gifts` field on `Npc` schema (`grep -n 'appreciated_gifts' packages/shared/src/entities/npc.ts` → 0). No gift-acceptance mechanic. | None | NOT_SHIPPED |
| Tavern entertainment (rounds, bards, gambling) | No tavern-economy code. Tavern narrated in DM prose only. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Endgame Sinks

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| Legendary item repair (200+sp) | Cross-ref Maintenance row above: NOT_SHIPPED. | None | NOT_SHIPPED |
| NPC resurrection service (1000+sp) | Cross-ref Combat Sinks row: NOT_SHIPPED. | None | NOT_SHIPPED |
| Faction investments (100+sp minimum, delayed returns) | Cross-ref story-003 faction-exclusive access audit: investments NOT_SHIPPED. | None | NOT_SHIPPED |
| Letter of Credit 5% interest | Cross-ref story-003 (Merchant Guild faction example): NOT_SHIPPED. | None | NOT_SHIPPED |
| Consignment 10% commission | Cross-ref story-004 consignment audit: NOT_SHIPPED. | None | NOT_SHIPPED |
| Warehouse Storage 2sp/week (Merchant Guild Trusted+) | Cross-ref story-003: NOT_SHIPPED. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Magnitude Analysis & Implementation

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| Per-category per-session drain estimate table (8 rows: Maintenance 5/15/50sp → Endgame 0/0/5000+sp; total typical ~150sp) | No telemetry. No aggregation surface. Magnitude analysis is unverifiable in shipped state. | None | NOT_SHIPPED |
| Faucet/sink balance check (quest tier 1 25-50sp + 2 100-250sp + 3 300-700sp → net +50 to +150 sp/session) | Faucet half (quest rewards) BUILT per story-001 quest_tools.py. Sink half NOT_SHIPPED. Balance equation has only one side. | None | NOT_SHIPPED |
| `sink_event` log schema {player_id, sink_category, sink_type, item_id, amount_sp, context, timestamp} | No `sink_event_log` table. `grep -rnE 'CREATE TABLE.*sink|sink_event' scripts/migrations/*.sql` → 0 matches. New table needed. | None | NOT_SHIPPED |
| Aggregation by category produces economic profile + world sink rate | Same — no aggregator. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Gap Analysis (5 proposals)

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| Gap 1: Companion equipment maintenance (~5-25 sp/session, half player cost) | No CompanionEquipment schema or hook. | None | NOT_SHIPPED |
| Gap 2: Bribery system (NPC accept threshold based on role + disposition + faction loyalty + stakes; 5-25sp small favors, 100+sp betrayals) | No bribery mechanic in code. No `bribe_npc(amount)` tool. | None | NOT_SHIPPED |
| Gap 3: Travel tolls (ferry 5sp/person, bridges 1-5sp, city entry 5sp, mountain pass guides 25sp — Decision 110 requires free alternative) | No toll mechanic. `content/locations.json` location exits have no toll cost. | None | NOT_SHIPPED |
| Gap 4: Property and Housing (Cottage 500sp/5sp_week, Townhouse 2000sp/20sp_week, Estate 10000sp/100sp_week) — Phase 2+ deferred | Spec defers to Phase 2+; no property schema, expected. | None | NOT_SHIPPED |
| Gap 5: NPC Gift System (`appreciated_gifts: string[]` field, disposition shifts) | No field on Npc schema. No accept-gift mechanic. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Design Decisions 105-113

Spec L408-428 records 9 architectural decisions. Spec L410 claims "Extracted to `game_mechanics_decisions.md` for canonical reference" — **fourth audit story to find the same false-extraction pattern** (story-002 found it for 96-104, story-003 for 82-86, story-004 for 87-95, this story for 105-113). The decisions log terminates at Decision 72. None encoded.

| Decision | Item (verbatim) | Status |
| --- | --- | --- |
| 105 | 8 sink categories with distinct design intents | NOT_SHIPPED |
| 106 | All forced sinks must have player-agency mitigations | NOT_SHIPPED (no forced-sink registry to enforce against) |
| 107 | Mortaen's death costs are non-monetary; gold sinks come from spell components + NPC services | NOT_SHIPPED (Mortaen system + spell components + services all NOT_SHIPPED) |
| 108 | Endgame sinks must absorb wealth at 1000+sp magnitudes | NOT_SHIPPED |
| 109 | Lifestyle sinks reward wealth without granting mechanical advantage | NOT_SHIPPED (no luxury content or lifestyle hooks ship) |
| 110 | Travel tolls must always have a free alternative | NOT_SHIPPED (no tolls) |
| 111 | Bribery is a real social mechanic, not just thematic | NOT_SHIPPED |
| 112 | Companion equipment maintenance is half player gear cost | NOT_SHIPPED |
| 113 | Sink event logging is required infrastructure for inflation control | NOT_SHIPPED (no log table; story-006 inflation will inherit) |

## Deliverables status (per 09_economy.md M9.x §Deliverables, cross-doc)

This audit story is doc-only and does not own M9.x deliverables directly — the capstone (story-008) will. Mapping for the capstone:

- 8-category sink framework: **NOT_SHIPPED** (no enum)
- 5-band lodging cost gating on rest: **NOT_SHIPPED** (rest BUILT, gating NOT_SHIPPED)
- `consume_item` hook firing gold-removal + inventory decrement: **DESIGNED↔aspirational** (item.effects + remove_from_inventory exist; auto-consume hook absent)
- `sink_event_log` table + aggregator: **NOT_SHIPPED**
- 5 gap-analysis additions (companion gear, bribery, tolls, property, NPC gifts): **NOT_SHIPPED** (property deferred to Phase 2+ per spec)
- 9 design decisions 105-113 encoded as constants: **NOT_SHIPPED**
- All per-row sink categories inherit from prior audits: **NOT_SHIPPED** (consolidated)

## Out-of-scope findings (Sprint-spec-cleanup punch list)

Routed to `audit/README.md` Sprint-006 section by capstone (story-008) per wisdom `d0715b09a1df`:

1. **`player.gold` is structurally one-write, no-read.** When the sink pipeline lands, the mutation surface (`add_gold` / `consume_gold` / `attempt_charge`) needs to exist alongside the read path. Capstone should call this out explicitly — the field has been there since character creation but the spend half doesn't exist.
2. **Add `consume_item` agent tool/function.** Bridges the gap between `item.effects[].type == 'heal'` data and the actual mechanic (HP add, item decrement, sink event). Without this, the DM can narrate a potion drink but the rules engine doesn't fire the consequences automatically.
3. **`apply_rest` should accept a `lodging_quality` parameter** that gates the +1 quality bonus and emits a sink_event. This is a small change to a BUILT function; high-leverage low-cost.
4. **Add `sink_event_log` table** (migration) — schema per spec L390-402. Required infrastructure for inflation control (story-006 will depend on this).
5. **Decisions 105-113 are NOT extracted to `game_mechanics_decisions.md`.** Fourth audit story finding the same false-extraction pattern. Combined implied undocumented decision count is now 35+ (73-81 + 87-95 + 96-104 + 105-113). Capstone bulk fix is overdue and should include identifying any other dormant extraction claims.
6. **Spec's faucet/sink balance check (L310) is unverifiable in shipped state** because only the faucet (quest rewards) ships. Capstone should record this as a M9.x acceptance dependency: balance verification can only land after enough sinks ship to make the equation 2-sided.
7. **5 gap-analysis additions need capstone disposition.** Property (gap 4) is explicitly Phase 2+. Bribery, tolls, companion gear, NPC gifts — capstone must decide whether to add to M9.x scope, defer, or fold into other milestones (e.g., bribery into Phase 2 social encounter resolution).
8. **`appreciated_gifts: string[]` field on Npc schema is a low-cost schema addition** that enables Gap 5 (NPC gifts) immediately. Capstone may bundle this with M9.x faction-pricing schema decisions (story-003 punch-list item 1) since both touch Npc.
9. **Per-NPC role determines bribery acceptability** (Decision 111 sub-rule). Cross-ref story-003 punch-list item 6 (NPC.faction affiliation field clarification) and Phase 6 NPC role archetypes (NOT_SHIPPED) — bribery is structurally downstream of role typing.

## Verification

Verified-at: 7ca287c3ab1cbd4a30619b6e42b79cb002704fe2

Grep commands used (all from repo root; 0 matches unless noted):

```bash
# Sink tracking infrastructure
grep -rnE 'sink_event|sink_log|gold_sink|sink_category|SinkCategory|SINK_CATEGORIES' apps/ packages/ scripts/migrations/
grep -rnE 'CREATE TABLE.*sink' scripts/migrations/*.sql

# Gold mutation surface
grep -rnE "gold.*-=|gold.*\\+=|update_gold|consume_gold|attempt_charge" apps/agent/

# Consume-item / on-consume hook
grep -rnE 'def.*consume_item|on_consume|item_consumed' apps/agent/

# Lodging cost gating
grep -rnE 'lodging_quality|inn_cost|pay_for_room|common_room.*sp|fine_room.*sp' apps/ packages/

# Gap-analysis additions
grep -rnE 'bribery|bribe_npc|travel_toll|toll_cost|property_purchase|housing_maintenance|appreciated_gifts' apps/ packages/ content/

# Confirmed-present substrate (returned matches):
grep -n 'starting_gold' apps/agent/creation_classes.py                              # 19 lines (1 field + 18 archetypes)
grep -n '"gold"' apps/agent/creation_rules.py                                       # L257 ("gold": cls.starting_gold)
grep -nE 'def apply_short_rest|def apply_long_rest|def apply_rest' apps/agent/rest_mechanics.py  # L8, L20, L32
grep -n 'innkeeper_maren' content/npcs.json                                          # L263

# 3 of 6 consumables shipping match (counted)
python3 -c "import json; items = json.load(open('content/items.json')); items = items['items'] if isinstance(items, dict) else items; cs = [i['id'] for i in items if i.get('type') == 'consumable']; print('consumable ids:', cs)"
# ['healing_potion', 'antidote_basic', 'holy_water', 'rations_basic', 'millhaven_provisions', 'restoration_salve']

# Decisions log terminates at Decision 72 (4th audit story to verify)
grep -nE '^## ' docs/game_mechanics/game_mechanics_decisions.md | tail -3
# "## Economy Reconciliation (Decision 72)" is the last
```
