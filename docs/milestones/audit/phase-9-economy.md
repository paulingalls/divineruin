# Phase 9 Audit — Economy base spec (Sprint-006 story-001)

Sprint-006 / Milestone 6 (story-001). Read-only audit of `docs/game_mechanics/game_mechanics_economy.md` (275 lines, 12 H2 sections) against shipped code in `apps/agent/`, `apps/server/src/`, `packages/shared/src/entities/`, `content/`, and `scripts/migrations/`. Status legend (matches sprint-004 audit/README.md L49-58): **BUILT** = code present and matches spec; **DESIGNED** = spec well-defined and partial code exists, but the symbol/feature is missing, renamed, or diverges; **NOT_SHIPPED** = no implementation found. Sibling sprint-006 audit files (planned): `phase-9-supply-demand.md` (story-002), `phase-9-faction-pricing.md` (story-003), `phase-9-restock.md` (story-004); `phase-9-gold-sink.md`/`phase-9-inflation.md`/`phase-9-p2p-trade.md` (stories 005-007 not yet scheduled).

Verified-at: 9d7a0e20e90b52564f80b00dc0b446770d3e5aab

## Summary

| Section | BUILT | DESIGNED | NOT_SHIPPED |
| --- | --- | --- | --- |
| Currency System (3-tier cp/sp/gc) | 0 | 1 | 1 |
| Economic Anchor (1 sp = 1 day labor) | 0 | 0 | 1 |
| Canonical Price Tables (5 categories, ~50 rows) | 0 | 1 | 5 |
| NPC Services (11 rows) | 0 | 0 | 1 |
| Workspace Rental (4 rows + disposition discount) | 0 | 0 | 1 |
| Crafting Commissions (3 tiers + 4 repair tiers) | 0 | 0 | 2 |
| Mentor Training Fees (5 ranges) | 0 | 1 | 0 |
| Starting Gold (2 categories) | 0 | 1 | 0 |
| Merchant Pricing Formula (5 modifiers + clamp + 5-tier disposition table) | 0 | 1 | 1 |
| Quest Reward Tiers (3 tiers) | 0 | 1 | 0 |
| Hollow Material Values (4 rows) | 0 | 0 | 1 |
| Currency Drops from Combat (cross-ref encounter_roles) | 0 | 0 | 1 |

**Headline finding:** Phase 9 base spec is **almost entirely NOT_SHIPPED at the mechanical layer**. The economy infrastructure as code is limited to four touchpoints: (1) `Item.value_base` + `value_modifiers` fields exist on the shared schema and are populated in `content/items.json` for ~12 typed items, but the denominations diverge sharply from spec — code values are 12-50× the spec sp prices, with no documented unit and no `convert_currency` to reconcile; (2) a single `starting_gold: int` field on `ArchetypeDefinition` (`apps/agent/creation_classes.py:21`) carries per-archetype starting wealth that **diverges from spec** (spec says 10 sp baseline / 15 sp Diplomat; code ships 5 values across 18 archetypes: 10/15/20/25 with Diplomat=25, Spy=25, Artificer=20, Rogue=20); (3) `Npc.disposition_modifiers?: Record<string, number>` exists on the schema and is populated in `content/npcs.json` (14 NPCs), but the field is **a different mechanic from the spec's 5-tier disposition price modifier** — code keys are event names like `defended_millhaven: 5` / `lied_about_findings: -4` (delta-to-disposition-score), not the price-multiplier table; (4) `player.gold: int` lives inside the JSONB `players.data` blob (`creation_rules.py:257`) — single untyped denomination, no cp/sp/gc separation. **Zero of 11 NPC services, 0 of 4 workspaces, 0 of 3 commission tiers + 4 repair tiers, 0 of 5 mentor fee bands, 0 of 5 disposition price modifiers, 0 of 3 quest reward tiers, 0 of 4 Hollow material tiers, and 0 currency-drop rules are encoded as resolvable symbols.** No DB migration touches an economy-flavored table (`scripts/migrations/001`-`017`, none match). No `convert_currency`, `lookup_base_price`, `calculate_merchant_price`, `clamp_price`, `apply_disposition_modifier`, or `repair_cost` symbol exists.

**Honesty note 1 — Item value denomination divergence.** Spec L82 sets weapon range 1-40 sp; code values range 20-500 with no spec sp scaling. Examples (spec → code, ratio): Short Sword 5 sp → `shortsword_basic` 100 (×20), Longsword 10 sp → `longsword_guild` 200 (×20), Dagger 2 sp → `dagger_balanced` 50 (×25), Mace 3 sp → `war_mace` 150 (×50), Leather 5 sp → `leather_armor_basic` 150 (×30), Chain Shirt 30 sp → `chain_shirt` 350 (×~12), Scale Mail 30 sp → `scale_mail` 500 (×~17). No consistent ×10 (cp), ×1 (sp), or ×100 (cp from gc) match. The content was authored against an earlier or independent pricing standard; the schema field is BUILT but the **anchor is unenforced**, content is divergent, and there is no spec-to-content reconciliation surface (no `lookup_base_price(item_id)` consuming `value_base`, no test asserting `value_base` is within spec range).

**Honesty note 2 — `disposition_modifiers` field name collision.** `Npc.disposition_modifiers?: Record<string, number>` (`packages/shared/src/entities/npc.ts:33`) and content like `guildmaster_torin: {completed_greyvale_quest_stage: 3, lied_about_findings: -4}` (`content/npcs.json:34+`) implement a **per-action disposition delta system** (event happened → adjust this NPC's disposition score toward this player). The spec's `disposition_modifier` (L218-225) is a **price multiplier table** keyed by disposition tier (Hostile +20% → Trusted -20%). Same field name, different mechanic. The code field does not affect prices; the spec's price-modifier table is NOT_SHIPPED. Capstone must reconcile: rename one or both, or extend the schema with a separate `price_modifiers` field.

**Honesty note 3 — `starting_gold` is unit-agnostic int.** Spec says 10 sp / 15 sp Diplomat. Code ships 18 archetype entries with values 10/15/20/25 (Warrior 15, Guardian 10, Skirmisher 15, Mage 10, Artificer 20, Seeker 15, Druid 10, Beastcaller 10, Warden 10, Cleric 15, Paladin 15, Oracle 10, Rogue 20, Spy 25, Whisper 15, Bard 15, Diplomat 25, Marshal 15). The value isn't suffixed (no `_sp`, no enum). Assuming sp, **5 of 18 archetypes match the spec baseline of 10**, **8 match the 15 Diplomat tier or above**, and **the named Diplomat exceeds the spec value by 10 sp**. Field is BUILT; values are DESIGNED↔aspirational.

## Coverage matrix

Spec sections under §gm_economy mapped to existing `09_economy.md` milestone items. **NEW** = spec content with no corresponding M9.x bullet.

| Spec section (file:line) | Milestone item | Notes |
| --- | --- | --- |
| Currency System (gm_economy.md:26-34) | M9.1 — three-tier currency model (10:1 ratio) | Spec defines cp/sp/gc with strict 10:1 step. Milestone L25-28 names same model. |
| Economic Anchor (gm_economy.md:36-46) | M9.1 — 1 sp = 1 day's unskilled labor | Spec L38 anchor. Milestone L26 names same constant. Derived benchmarks (laborer/skilled/expert wage scale) at gm_economy.md:43-45 = milestone M9.1 L29. |
| Canonical Price Tables — Food & Lodging (gm_economy.md:51-59) | M9.1 — 14 categories with ≥3 items each | Spec ships 5 rows for Food & Lodging (gm_economy.md:55-59). |
| Canonical Price Tables — Weapons (gm_economy.md:61-82) | M9.1 — 14 categories with ≥3 items each | Spec ships 16 weapon rows (1-40 sp range). |
| Canonical Price Tables — Armor (gm_economy.md:84-99) | M9.1 — 14 categories with ≥3 items each | Spec ships 10 armor rows (3 sp to 100 gc). |
| Canonical Price Tables — Adventuring Gear (gm_economy.md:101-121) | M9.1 — 14 categories with ≥3 items each | Spec ships 15 gear rows (1 cp to 15 sp). |
| Canonical Price Tables — Spell Components (gm_economy.md:123-129) | M9.1 — 14 categories with ≥3 items each | Spec ships 2 rows (Revivify/Resurrection diamonds). **Diverges from milestone** L23 "14 categories with ≥3 items each" — Spell Components only has 2. |
| NPC Services (gm_economy.md:132-148) | NEW (cross-ref M9.2 merchant pricing) | Milestone 9.1-9.3 do not enumerate the NPC service price list (11 rows: Heal Wounds, Cure Poison, Dispel Corruption, Remove Curse, Greater Restoration, Resurrection, Identify ×2, Research ×2, Translate). Spec L132-148. **Capstone should add as new M9.x.** |
| Workspace Rental (gm_economy.md:152-161) | NEW (cross-ref Phase 5 M5.2 workspaces) | Milestone 9.1-9.3 omit workspace pricing. 4 rows + disposition discount (Friendly 80%, Trusted 60%, Standing free). **Capstone should add.** |
| Crafting Commissions (gm_economy.md:165-180) | NEW (cross-ref Phase 5 crafting) | 3 tiers × 2 sourcing modes + 4 repair tiers (Common 2 sp → Legendary 200+ sp). **Capstone should add.** |
| Mentor Training Fees (gm_economy.md:184-192) | NEW (cross-ref Phase 6 M6.3 mentors) | 5 fee bands (15-20 sp informal → 80-100 sp legendary, 0 sp honor-based). Phase 6 mentor audit (`phase-6-mentors.md`) marked mentor registry NOT_SHIPPED; **fee structure inherits that status**. |
| Starting Gold (gm_economy.md:196-203) | M9.1 — starting gold by archetype | Milestone L28 says "Starting gold by archetype: 10 sp (most archetypes), 15 sp (Diplomat)". Code ships 5-value spread 10/15/20/25 with Diplomat=25 — see honesty note 3. |
| Merchant Pricing Formula (gm_economy.md:207-234) | M9.2 — merchant pricing engine | Milestone L55-71 names same formula. Spec stacking + 0.5×–3.0× clamp + 5-tier disposition table. None shipped. |
| Quest Reward Tiers (gm_economy.md:238-246) | M9.3 — quest reward calibration | Milestone L86-92. 3 tiers (25-50 sp / 100-250 sp / 300-700 sp). Quests exist in `content/quests.json` but lack tier-keyed reward calibration. |
| Hollow Material Values (gm_economy.md:250-261) | NEW (cross-ref Sprint-003 encounter_roles audit) | 4 tiers (Drift 5-15 sp → Wrack 200-500 sp → named fragments 500 sp). Sprint-003 `phase-encounter-roles.md` already flagged material sell values as out of milestone scope. **Capstone should formalize as M9.x.** |
| Currency Drops from Combat (gm_economy.md:265-275) | NEW (cross-ref encounter_roles M9.4 deferred) | 5 category rules (beasts/humanoids/Hollow Drift/Hollow Rend+/undead) + encounter-role modifiers. Pre-existing audit cross-ref note in `09_economy.md:13-19` already flags M9.4 deferred. |

## Audit Status (Sprint-006) — Currency System

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| Three-tier decimal currency: cp (10 cp = 1 sp), sp baseline, gc (1 gc = 10 sp) | No `Currency` / `Denomination` enum or class. `grep -rnE 'class Currency\|enum Currency\|Denomination\|copper_pieces\|gold_crowns\|silver_pieces' apps/ packages/` → 0 matches. `player.gold: int` is a single untyped integer field inside `players.data` JSONB (set at `apps/agent/creation_rules.py:257`). `Item.value_base: number` (`packages/shared/src/entities/item.ts:20`) is also unit-agnostic. Three denominations, zero code representation. | None | NOT_SHIPPED |
| `gp` denomination explicitly does not exist (Aethos lore) | Negative constraint. `grep -rni '\bgp\b' apps/agent apps/server/src packages/shared/src` → no hits in active source. Honored by absence. (Some content/transcripts log strings mention "coin" generically but never `gp`.) | None | DESIGNED |

## Audit Status (Sprint-006) — Economic Anchor

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| 1 sp = 1 day's unskilled labor (canonical reference, all pricing validated against this anchor) | No constant. `grep -rnE 'DAY_LABOR\|UNSKILLED_LABOR\|ECONOMY_ANCHOR\|sp_per_day' apps/ packages/` → 0 matches. No wage scale (1 sp / 1.5 sp / 2-3 sp daily) is encoded. Anchor is documentation-only; nothing in code consumes or asserts it. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Canonical Price Tables

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| Food & Lodging — 5 rows, 5 cp to 15 sp | No content for inn/lodging/rations rates. `grep -rnE 'rations\|lodging\|common_room\|private_room\|waterskin' apps/agent content/` → 0 priced entries. | None | NOT_SHIPPED |
| Weapons — 16 rows, 1 sp to 40 sp | Schema BUILT (`Item.value_base`, `value_modifiers` at `item.ts:20-21`). Content **partial + divergent**: `content/items.json` ships 4 weapons (`shortsword_basic`=100, `longsword_guild`=200, `dagger_balanced`=50, `quarterstaff_oak`=20, `war_mace`=150, `hunting_bow`=125, `hollow_edge_blade`=0). Of 16 spec weapons, 6 appear in content but values diverge from spec sp by 12-50× with no consistent scaling (see honesty note 1). Missing: spear, staff, handaxe, battleaxe, warhammer, rapier, shortbow, light crossbow, greatsword, longbow, heavy crossbow, hand crossbow. | None — no `value_base` assertion test exists. | DESIGNED |
| Armor — 10 rows, 3 sp to 100 gc | Same schema BUILT. Content partial + divergent: 4 armor pieces (`leather_armor_basic`=150, `chain_shirt`=350, `shield_iron`=120, `scale_mail`=500, `travelers_cloak`=200). Missing: padded, hide, studded leather, chain mail, half plate, plate. Half plate / plate at 50-100 gc (500-1000 sp) entirely absent — the rare-tier widening from milestone deliverable L31 ("Range: 3 sp to 100 gc") is unshipped. | None | DESIGNED |
| Adventuring Gear — 15 rows, 1 cp to 15 sp | No torch/rope/bedroll/backpack content. None of the 15 gear rows ship as content with a `value_base`. | None | NOT_SHIPPED |
| Spell Components — 2 rows (Revivify diamond 50 gc, Resurrection diamond 500 gc) | No content for either. Milestone L23 "14 categories with ≥3 items each" diverges from spec (Spell Components has only 2 items — capstone follow-up). | None | NOT_SHIPPED |
| DB seed populates canonical price reference table | Negative — no migration creates a `price_reference` / `canonical_prices` table. `grep -nE 'CREATE TABLE.*(price\|currency\|merchant\|economy)' scripts/migrations/*.sql` → 0 matches. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — NPC Services

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| 11 NPC service price points (Heal Wounds 5 sp → Resurrection 1,000+ sp) | No service catalog. `grep -rnE 'def.*heal_wounds\|def.*cure_poison\|def.*dispel_corruption\|def.*remove_curse\|def.*greater_restoration\|def.*identify_item\|def.*identify_hollow\|def.*research_\|def.*translate_text' apps/agent/` → 0 matches. NPCs have no `services[]` field on the schema (`packages/shared/src/entities/npc.ts`). One narrative mention only: `content/npcs.json:474` "healing services available at the temples" — prose, not data. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Workspace Rental

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| 4 workspace daily rates (Workshop 2 sp/d → Forge+Lab 12 sp/d) + disposition discount tiers (Friendly 80%, Trusted 60%, Standing free) | No workspace rental data. `grep -rnE 'workshop_rate\|forge_rate\|lab_rate\|workspace_rental\|rental_price' apps/ content/ packages/` → 0 matches. Phase 5 crafting audit (`phase-5-recipes-resolution.md`) already marked workspace_types NOT_SHIPPED at the type layer; pricing inherits that status. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Crafting Commissions

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| NPC blacksmith commission pricing — 3 tiers × 2 sourcing modes (player-materials vs smith-provides) | No commission price table. `grep -rnE 'commission_price\|crafting_commission\|tier_1_commission' apps/ content/` → 0 matches. Phase 5 audit marked the broader crafting resolution as NOT_SHIPPED. | None | NOT_SHIPPED |
| Repair pricing — 4 tiers (Common 2 sp → Legendary 200+ sp) | No repair function or content. `grep -rnE 'repair_price\|repair_cost\|def.*repair' apps/agent/` → 0 matches. Phase 5 durability audit (`phase-5-durability.md`) noted durability mechanics NOT_SHIPPED; repair pricing depends on durability landing first. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Mentor Training Fees

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| 5 fee bands (15-20 sp informal → 80-100 sp legendary, 0 sp honor-based) | Phase 6 audit (`phase-6-mentors.md`) marked the mentor registry **DESIGNED** (training-cycle state machine BUILT via migration 016/017; mentor-variant registry NOT_SHIPPED). Fee structure inherits **DESIGNED↔aspirational** status: training cycle infrastructure can carry a `fee_sp` field on `content/training_programs.json` entries but does not today. `grep -nE 'fee\|cost\|price' content/training_programs.json` → 0 matches. The 4 shipped training programs ship without fees. | None | DESIGNED |

## Audit Status (Sprint-006) — Starting Gold

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| Most archetypes 10 sp / Diplomat 15 sp | `apps/agent/creation_classes.py:21` defines `starting_gold: int` field on `ArchetypeDefinition`. 18 archetype entries ship values 10/15/20/25 with **Diplomat=25** (spec=15). Spec spread is 2 values; code spread is 4 values; named Diplomat at 25 sp **diverges from spec by +10 sp**. Field is BUILT; spec alignment is DESIGNED↔divergent. `creation_rules.py:257` applies via `"gold": cls.starting_gold` to the new player dict — single untyped int, no cp/sp/gc separation. | None — no test asserts spec-aligned values. | DESIGNED |

## Audit Status (Sprint-006) — Merchant Pricing Formula

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| `final_price = base_price × disposition × faction × event × context` with 0.5×–3.0× clamp | No `calculate_price` / `merchant_pricing` / `apply_pricing_modifiers` / `clamp_price` function. `grep -rnE 'def.*calculate_price\|def.*merchant_price\|def.*clamp_price' apps/agent/` → 0 matches. Modifier-stacking and clamp are mathematical operations defined only in spec. | None | NOT_SHIPPED |
| Disposition modifier table (5-tier: Hostile +20% → Trusted -20%) | **Field-name collision with shipped mechanic** (see honesty note 2). `Npc.disposition_modifiers?: Record<string, number>` ships on the schema (`npc.ts:33`) and is populated for 14 NPCs in `content/npcs.json`, but the field carries per-action disposition deltas (e.g. `defended_millhaven: 5`), not price multipliers. Spec's 5-tier price-modifier table is structurally absent. Schema reuse opportunity: extend `Npc` with a separate `price_disposition_modifiers` or rely on a global tier→multiplier constant table. | None | DESIGNED |

## Audit Status (Sprint-006) — Quest Reward Tiers

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| 3 reward tiers (25-50 sp / 100-250 sp / 300-700 sp) | `content/quests.json` defines 3 quests (`greyvale_anomaly`, `investigate_aldric`, `defend_millhaven`) with stages containing `rewards` arrays. `apps/agent/quest_tools.py:138-167` processes rewards (`xp_reward = on_complete.get("xp", 0)`). Quest reward processing infrastructure is **BUILT** for XP; quest reward currency calibration is **NOT_SHIPPED** — no tier classification on quests, no spec-tier-keyed `currency_reward` field on stages, no `assign_quest_tier` function. Status: DESIGNED↔aspirational — the data plumbing exists, the spec's tiered scale doesn't anchor it. | None | DESIGNED |

## Audit Status (Sprint-006) — Hollow Material Values

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| 4 tiers (Drift 5-15 sp → Rend 50-100 sp → Wrack 200-500 sp → Named fragments 500 sp fixed) | `content/items.json` ships `hollow_bone_fragment` with `value_base: 50` (matches Drift tier upper bound × ~5 if cp; matches no tier cleanly if sp). No `material_tier` field on Item, no Hollow-tier-keyed lookup. Sprint-003 encounter_roles audit (`phase-encounter-roles.md`) already flagged the broader Material Sell Values framework as out of milestone scope; this row inherits NOT_SHIPPED for the tiered structure. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Currency Drops from Combat

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| 5 category rules (beasts/humanoids/Hollow Drift/Hollow Rend+/undead) + encounter-role modifiers (Minions 0, Bosses 2× + bonus) | `09_economy.md:13-19` cross-ref note (sprint-003 capstone) already records that the currency-drop framework is owned by `game_mechanics_encounter_roles.md` §Loot Modifiers and that an M9.4 "Loot-side Economy" milestone was **deferred to the Phase 09 rewrite** (the current sprint). Code probe: `grep -rnE 'calculate_currency_drop\|currency_drop\|loot_currency' apps/agent/` → 0 matches. No tier×biome currency yield matrix in code. Sprint-006 capstone (story-008) **must absorb** this row into the rewritten M9.4. | None | NOT_SHIPPED |

## Deliverables status (per 09_economy.md M9.1 §Deliverables L25-36)

- Currency model cp/sp/gc with 10:1 ratio: **NOT_SHIPPED** (no enum / no separation; single untyped int)
- Economic anchor constant (1 sp = 1 day labor): **NOT_SHIPPED**
- Wage scale (1 / 1.5 / 2-3 sp/day): **NOT_SHIPPED**
- Canonical price tables across 14 categories: **DESIGNED↔aspirational** for weapons + armor (schema BUILT, content partial + divergent — see honesty note 1); **NOT_SHIPPED** for food/lodging, adventuring gear, spell components, food, tools, transport, clothing, services prep, potions/components, workspaces, animals, containers, misc gear
- Starting gold by archetype: **DESIGNED↔aspirational** (field BUILT; spec spread of 2 values shipped as 4 values 10/15/20/25, Diplomat diverges by +10 sp)
- DB seed canonical price reference: **NOT_SHIPPED**
- `convert_currency(amount, from, to)`: **NOT_SHIPPED**
- `lookup_base_price(item_id)`: **NOT_SHIPPED** (Item.value_base exists but no lookup helper)

## Deliverables status (per 09_economy.md M9.2 §Deliverables L55-71)

- Merchant pricing formula (5 modifiers + clamp): **NOT_SHIPPED**
- 5-tier disposition modifier table: **DESIGNED↔aspirational** (field name `disposition_modifiers` ships on Npc but carries a different mechanic — honesty note 2)
- Faction modifier table: **NOT_SHIPPED** (cross-ref story-003 phase-9-faction-pricing.md)
- Event modifier hook: **NOT_SHIPPED** (cross-ref story-002 phase-9-supply-demand.md)
- Regional/context modifier: schema partially BUILT (`Item.value_modifiers?: Record<string, number>`) with content keys like `faction:aelindran_diaspora: 2.0`, `npc:scholar_emris: 3.0` on `hollow_bone_fragment` — **DESIGNED↔confirmed** for the field, no formula consumes it
- 0.5×–3.0× clamp: **NOT_SHIPPED**

## Deliverables status (per 09_economy.md M9.3 §Deliverables L86-92)

- Quest reward tier classification: **NOT_SHIPPED** (no `tier` field on quests)
- Tier-keyed reward calibration (25-50 / 100-250 / 300-700 sp): **NOT_SHIPPED**
- Quest reward XP correlation: out of M9.3 scope (deferred per spec L246)
- Quest reward processing pipeline: **BUILT** (`quest_tools.py:138-167` processes rewards arrays); spec-tier alignment NOT_SHIPPED

## Out-of-scope findings (Sprint-spec-cleanup punch list)

These will be filed in `docs/milestones/audit/README.md` Sprint-006 section per wisdom `d0715b09a1df` — not in this story's body:

1. `09_economy.md:23` claims "14 categories with ≥3 items each" for canonical price tables, but spec §Spell Components has only 2 items. Capstone should reconcile (either drop Spell Components from the "≥3 items each" count or extend spec).
2. NPC Services, Workspace Rental, Crafting Commissions, Mentor Training Fees, Hollow Material Values, and Currency Drops from Combat are **all in the spec but absent from the 21-item milestone scope**. Capstone (story-008) should add as new M9.x subsections per execution_plan.json milestone-6 goal.
3. `Npc.disposition_modifiers` field-name collision with spec disposition-tier price modifier — capstone should rename or add a separate `price_disposition_modifiers` field (or use a global constant table). See honesty note 2.
4. `Item.value_base` denomination is undocumented in `item.ts`. Schema comment + a `lookup_base_price` helper would anchor the field to spec sp.
5. `starting_gold` spec divergence (Diplomat 25 vs spec 15; 4-value spread vs spec 2-value) — capstone should either reconcile the spec or annotate the divergence as intentional.

## Verification

Verified-at: 9d7a0e20e90b52564f80b00dc0b446770d3e5aab

Grep commands used (all from repo root, all returned 0 matches unless noted):

```bash
# Currency type/denomination separation
grep -rnE 'class Currency|enum Currency|Denomination|copper_pieces|gold_crowns|silver_pieces' apps/ packages/

# Economy anchor / wage scale
grep -rnE 'DAY_LABOR|UNSKILLED_LABOR|ECONOMY_ANCHOR|sp_per_day' apps/ packages/

# Merchant pricing / clamp / formula
grep -rnE 'def.*calculate_price|def.*merchant_price|def.*clamp_price|def.*apply_pricing' apps/agent/
grep -rnE 'convert_currency|lookup_base_price' apps/ packages/

# NPC services
grep -rnE 'def.*heal_wounds|def.*cure_poison|def.*dispel_corruption|def.*remove_curse|def.*greater_restoration|def.*identify_item|def.*identify_hollow|def.*research_|def.*translate_text' apps/agent/

# Workspace rental
grep -rnE 'workshop_rate|forge_rate|lab_rate|workspace_rental|rental_price' apps/ content/ packages/

# Crafting commissions / repair
grep -rnE 'commission_price|crafting_commission|tier_1_commission|repair_price|repair_cost|def.*repair' apps/ content/

# Currency drops from combat
grep -rnE 'calculate_currency_drop|currency_drop|loot_currency' apps/agent/

# Economy-flavored migrations (0 matches expected)
grep -nE 'CREATE TABLE.*(price|currency|merchant|economy)' scripts/migrations/*.sql

# Confirmed-present symbols (returned matches):
grep -n 'starting_gold' apps/agent/creation_classes.py      # 19 lines (1 field decl + 18 archetype entries)
grep -n 'value_base\|value_modifiers' packages/shared/src/entities/item.ts   # 2 lines (L20-21)
grep -n 'disposition_modifiers' packages/shared/src/entities/npc.ts content/npcs.json   # 1 + 14 lines

# Item value_base spec divergence (content listing)
python3 -c "import json; d=json.load(open('content/items.json')); items=d['items'] if isinstance(d,dict) else d; print([(i['id'],i.get('value_base')) for i in items if i.get('type') in ('weapon','armor')])"
```
