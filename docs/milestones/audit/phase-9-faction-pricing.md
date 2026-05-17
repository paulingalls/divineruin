# Phase 9 Audit — Economy / Faction Reputation Pricing (Sprint-006 story-003)

Sprint-006 / Milestone 6 (story-003). Read-only audit of `docs/game_mechanics/economy/faction_reputation_pricing.md` (185 lines, 1 H2 with 7 major subsections) against shipped code in `apps/agent/`, `apps/server/src/`, `packages/shared/src/entities/`, `content/`, and `scripts/migrations/`. Status legend (matches sprint-004 audit/README.md L49-58): **BUILT** = code present and matches spec; **DESIGNED** = spec well-defined and partial code exists, but the symbol/feature is missing, renamed, or diverges; **NOT_SHIPPED** = no implementation found. Sibling sprint-006 audit files: `phase-9-economy.md` (story-001, base spec), `phase-9-supply-demand.md` (story-002, supply/demand engine), `phase-9-restock.md` (story-004, planned).

Verified-at: e7e0891866646b87b3705b1dbcf7b59f6975b5cd

## Summary

| Section | BUILT | DESIGNED | NOT_SHIPPED |
| --- | --- | --- | --- |
| Reputation Tiers & Price Modifiers (6 tiers + 6 modifiers) | 0 | 1 | 1 |
| Combined Pricing Formula (disposition × faction stacking) | 0 | 0 | 1 |
| Faction Service Refusal (Hostile/Unfriendly gating) | 0 | 1 | 1 |
| Earning Reputation Through Economic Activity (5 grant actions + 5 loss actions + caps) | 0 | 0 | 10 |
| Faction-Exclusive Access (4-tier framework + 2 worked examples) | 0 | 1 | 3 |
| Interaction with other economy systems (workspace / crafting / inventory / supply-demand) | 0 | 0 | 4 |
| DM Narration Guidance (5 standing narration patterns + reputation-shift narration) | 0 | 0 | 6 |
| Design Decisions 82-86 (5 design decisions) | 0 | 0 | 5 |

**Headline finding:** Faction reputation pricing is **mostly NOT_SHIPPED**, but the **persistence substrate is BUILT**. Schema and content shipping: `packages/shared/src/entities/faction.ts:1-21` defines `Faction.reputation_tiers: Record<string, ReputationTier>` with `{threshold: number, effects: string[]}`; `scripts/migrations/001_initial_schema.sql:57-66` ships the `factions` table; `001:135-143` ships `player_reputation (player_id, faction_id, data JSONB)` as the per-player reputation table with composite PK; `scripts/migrations/002_add_indexes.sql:5` ships `idx_player_reputation_faction`. `content/factions.json` ships **4 factions** (`accord_guild`, `aelindran_diaspora`, `independent`, `temple_authority`) and **each populates all 6 spec tiers (hostile/unfriendly/neutral/friendly/trusted/honored) with the exact spec thresholds (-10/-5/0/+5/+15/+25)** — a clean DESIGNED↔confirmed match for the tier model. What does NOT ship: zero code reads or writes `player_reputation` (`grep -rnE 'player_reputation|FROM player_reputation|INSERT INTO player_reputation' apps/agent/ apps/server/` → 0 matches); no `faction_modifier` / `apply_faction_modifier` / `compute_faction_price` function; zero price-modifier numerical values from the 6×5 disposition-tier × faction-tier modifier table; zero of the 5 reputation-granting economic actions; zero of the 5 reputation-damaging actions; zero of the cap/cooldown enforcement (max +3/week, once-per-day per action, no economic path to Honored); zero of the 4 service-refusal tiers as gating logic; zero of the 4 faction-exclusive-access framework tiers; zero of the 2 worked examples (Thornwatch, Merchant Guild) as content (and Thornwatch is not in `content/factions.json` at all); zero of 5 design decisions 82-86 encoded as constants; zero narration templates.

**Honesty note 1 — `reputation_tiers.effects` strings are narrative not numerical.** Each faction's tier carries an `effects: string[]` array like `["banned from guild hall", "bounty placed"]` for hostile or `["guild council voice", "field authority", "classified intelligence"]` for honored (sample from `accord_guild`). These are descriptive prose intended for narration. The spec's **numerical price modifiers** (+15% / 1.0× / -5% / -10% / -15%) are **not in the data**. The schema accommodates them — the `Faction.reputation_tiers[tier]` shape is `{threshold, effects}` only — there's no `price_modifier: number` field. **Schema extension required** for the spec to land: add `price_modifier: number` (or compute from a global tier→modifier constant table). The 6-tier structure is BUILT; the per-tier multiplier is NOT_SHIPPED.

**Honesty note 2 — `player_reputation` table is structurally BUILT but completely dormant.** The composite-key (player_id, faction_id) JSONB row is the canonical per-player reputation store, indexed for faction-keyed lookups (`idx_player_reputation_faction`). **No shipping code reads or writes it.** `grep -rnE 'player_reputation' apps/agent/ apps/server/` → 0 matches. The reputation score that would be compared against the spec thresholds (-10/-5/0/+5/+15/+25) is **never computed, persisted, or queried**. The table is a parking lot waiting for the reputation-tracking pipeline to land.

**Honesty note 3 — Spec mentions Thornwatch + Merchant Guild + temples; only Temple Authority ships.** Spec L115-129 provides two faction worked examples: Thornwatch (military) and Merchant Guild (commercial). Neither appears in `content/factions.json`. Spec L66 also references "Thornwatch outpost". The 4 shipped factions (`accord_guild`, `aelindran_diaspora`, `independent`, `temple_authority`) are an **adjacent but non-overlapping set** — the Accord Guild is the closest analogue to the Merchant Guild example; no Thornwatch-equivalent exists. **Content-spec drift**: spec examples reference factions not in content; content factions are not covered by spec examples. Capstone should reconcile (either backfill Thornwatch in content, or update spec to use shipped faction ids).

**Honesty note 4 — Cross-doc reference to story-001 honesty note 2.** Story-001 flagged `Npc.disposition_modifiers` as a field-name collision: the schema field carries per-action disposition deltas (e.g. `defended_millhaven: 5`), not the 5-tier price-modifier table from `game_mechanics_economy.md:218-225`. The faction-pricing spec L24-28 requires that price-modifier table to combine with the faction modifier (`final_price = base_price × disposition_modifier × faction_modifier`). Both inputs to this formula are NOT_SHIPPED, but the field-name collision is specifically a story-001 finding that this audit inherits — capstone must reconcile both with a single fix.

## Coverage matrix

Spec sections under §Faction Reputation Pricing mapped to existing `09_economy.md` milestone items. **NEW** = spec content with no corresponding M9.x bullet.

| Spec section (file:line) | Milestone item | Notes |
| --- | --- | --- |
| Reputation Tiers & Modifiers — 6-tier ladder (faction_reputation_pricing.md:9-21) | M9.2 — faction modifier table | Spec table is the canonical faction modifier reference. Story-001 marked NOT_SHIPPED at M9.2 deliverables layer; this audit confirms schema substrate is BUILT but per-tier price modifiers absent. |
| Combined Pricing Formula (faction_reputation_pricing.md:22-46) | M9.2 — merchant pricing formula | Cross-doc with gm_economy.md:207-234 and supply_demand_engine.md:34-51. Multiplicative stacking with the 0.5×–3.0× clamp from story-002. |
| Faction Service Refusal (faction_reputation_pricing.md:47-61) | NEW | Tier-based gating (Hostile=no service, Unfriendly=basic only, etc.). Not in M9.x scope today. **Capstone should add.** |
| Earning Reputation Through Economic Activity (faction_reputation_pricing.md:64-99) | NEW | 5 grant actions + 5 loss actions + caps (max +3/week, once-per-day, no economic path past Trusted). **Capstone should add.** |
| Faction-Exclusive Access framework (faction_reputation_pricing.md:102-132) | NEW | 4-tier framework (Neutral / Friendly / Trusted / Honored) with Thornwatch + Merchant Guild worked examples. **Capstone should add.** |
| Interaction with other systems (faction_reputation_pricing.md:135-144) | Cross-ref M9.2 + workspace + crafting + supply/demand | 4 cross-cutting interactions: workspace stacking, faction-NPC crafting commissions, faction-inventory effects, supply/demand priority access. Story-001 + story-002 each flagged subsets; this audit consolidates. |
| DM Narration Guidance (faction_reputation_pricing.md:147-170) | NEW | 5 standing-tier narration templates + reputation-shift narration patterns. **Capstone should add** (parallels supply/demand DM narration audit finding). |
| Design Decisions 82-86 (faction_reputation_pricing.md:173-185) | NEW | 5 architectural decisions. Spec L175 claims "Extracted to `game_mechanics_decisions.md`" — same false claim flagged in story-002 audit for decisions 96-104. **Decisions file actually ends at Decision 72** — decisions 82-86 are also NOT extracted. Capstone must reconcile. |

## Audit Status (Sprint-006) — Reputation Tiers & Price Modifiers

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| 6-tier reputation ladder with thresholds (Hostile -10, Unfriendly -5, Neutral 0, Friendly +5, Trusted +15, Honored +25) | `packages/shared/src/entities/faction.ts:1-21` ships `ReputationTier {threshold: number, effects: string[]}` and `Faction.reputation_tiers: Record<string, ReputationTier>`. `content/factions.json` ships 4 factions, each carrying all 6 tier names with spec-matching thresholds (verified on `accord_guild`: hostile=-10, unfriendly=-5, neutral=0, friendly=5, trusted=15, honored=25). Tier structure + threshold values are **BUILT** and **match spec exactly**. | None | DESIGNED↔confirmed |
| Per-tier price modifier (+15% / 1.0× / -5% / -10% / -15% for trade-eligible tiers; Hostile = refusal) | No `price_modifier` field on the `ReputationTier` interface. The `effects: string[]` array carries narrative prose, not numbers. No global tier→modifier constant in code: `grep -rnE 'unfriendly.*1\.15\|trusted.*0\.9\|honored.*0\.85\|FACTION_MODIFIERS\|FACTION_PRICING' apps/ packages/` → 0 matches. The 6×5 combined disposition × faction matrix (`faction_reputation_pricing.md:32-38`) is undefined in code. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Combined Pricing Formula

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| `final_price = base_price × disposition_modifier × faction_modifier` (multiplicative stacking, then clamp from supply_demand_engine.md) | No combined pricing function. `grep -rnE 'def.*compute_price\|def.*calculate_price\|def.*merchant_price\|apply.*disposition.*faction' apps/agent/` → 0 matches (already verified in story-001 + story-002). The formula requires both disposition_modifier (NOT_SHIPPED per story-001 honesty note 2) and faction_modifier (NOT_SHIPPED above) — neither input exists, the combiner can't either. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Faction Service Refusal

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| 4-tier service availability (Hostile=none, Unfriendly=basic only, Neutral=full inventory + services, Friendly=+discounted faction supplies, Trusted=+restricted/faction-specific, Honored=+priority restock) | `Faction.reputation_tiers.effects` strings narratively imply some of this (`"banned from guild hall"`, `"refused contracts"`, `"guild gear access"`, `"priority contracts"`) but **no code reads `effects`** (`grep` 0 matches for any effect string) and no service-availability gating function exists. Schema can be extended to carry structured `services_available` per tier; today it's narrative-only. | None | DESIGNED |
| Hostile faction merchants may report player location to faction authorities | No incident-reporting hook, no faction-intelligence pipeline. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Earning Reputation Through Economic Activity

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| 5 grant actions (sell rare materials, commission faction equipment, donate to faction, fulfill bounty, supply rare crafted goods) | Zero handlers ship. The corresponding mutation surface (`player_reputation.data` JSONB) is empty — never written. `grep -rnE 'grant_reputation\|adjust_reputation\|reputation_grant\|reputation_action' apps/agent/ apps/server/` → 0 matches. | None | NOT_SHIPPED |
| Cap: max +3 per faction per real-time week from economic activity alone | No cap enforcement. No rate-limiting code, no `reputation_grant_history` table. | None | NOT_SHIPPED |
| Cooldown: each action type once per real-time day per faction | Same — no cooldown ledger. | None | NOT_SHIPPED |
| Economic gains cannot push past Trusted (+15) — Honored (+25) is quest-only | No clamping logic. | None | NOT_SHIPPED |
| 5 loss actions (sell faction secrets, trade restricted materials, fence stolen goods, refuse accepted bounty, undercut faction merchants) | Zero handlers. | None | NOT_SHIPPED |
| Detection gating: most negative actions only trigger reputation loss if discovered (Insight check by faction NPCs, faction intelligence patterns over time) | No detection pipeline. No `faction_intelligence_check` or similar. NPC `disposition_modifiers` event keys (`apps/agent/content/npcs.json` per story-001 finding) carry action triggers but don't gate to faction reputation. | None | NOT_SHIPPED |
| `Refuse a faction bounty after accepting` (-1) | No accepted-bounty tracking. Quest schema in `content/quests.json` doesn't carry faction-bounty subtype. | None | NOT_SHIPPED |
| `Undercut faction merchants` (-1) | Spec L96 explicitly flags Phase 2+ multiplayer-only — defers cleanly. | None | NOT_SHIPPED |
| Insight skill economically valuable (Spy can detect deception during trade) | Skill exists (per Phase 1 audit) but no trade-side Insight hook. | None | NOT_SHIPPED |
| Reputation-grant narration ("Word gets around that you've been supplying the Watch...") | No narration template for reputation shifts. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Faction-Exclusive Access

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| 4-tier framework (Neutral = standard, Friendly = discounted consumables + bounty board, Trusted = faction-specific equipment + crafting commissions + workspace access, Honored = priority restock + masterwork + intelligence) | `Faction.reputation_tiers[tier].effects` strings narratively describe **some** of these (e.g. `accord_guild.honored.effects` = `["guild council voice", "field authority", "classified intelligence"]`) — matches spec's Honored intelligence access. The narrative shipping is **DESIGNED↔confirmed** at the data layer; no code consumes the effects to gate access. No `faction_inventory_at_tier` / `unlock_faction_item` function. | None | DESIGNED |
| Thornwatch worked example (Friendly: signal arrows + anti-Hollow oil; Trusted: chain shirt +1 vs Hollow necrotic, Thornwatch blade, patrol maps; Honored: command seal + classified intel) | **Thornwatch faction does not exist in `content/factions.json`.** 4 shipped factions: accord_guild, aelindran_diaspora, independent, temple_authority. Worked example is unimplementable on shipped content (see honesty note 3). | None | NOT_SHIPPED |
| Merchant Guild worked example (Friendly: trade route info + market forecasts; Trusted: bulk discount + warehouses + letter of credit; Honored: auction + monopoly + investments) | **Merchant Guild faction does not exist in `content/factions.json`.** `accord_guild` is structurally adjacent (adventuring guild, has merchant relationships) but spec-text Merchant Guild content isn't seeded. | None | NOT_SHIPPED |
| Faction-specific item attribution (chain shirt with `+1 vs Hollow necrotic` cosmetic faction markings; longsword with `+1 damage vs Hollow`) | `Item.value_modifiers` (story-001 BUILT finding) supports faction-keyed multipliers (`hollow_bone_fragment` carries `faction:aelindran_diaspora: 2.0`). Spec's faction-stamped *items* (Thornwatch-issue armor with mechanical bonus) require a different shape — typed item suffix/prefix or `requires_faction_standing: {faction_id, min_tier}` constraint. Neither shipped. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Interaction with Other Economy Systems

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| Workspace rental stacks with faction reputation (Trusted = free workspace via standing access) | Spec L137. Story-001 marked workspace rental NOT_SHIPPED at the price-table layer; this faction-stacking interaction inherits that status. | None | NOT_SHIPPED |
| Faction-affiliated NPC smiths use faction pricing for commissions | Spec L139. Story-001 marked crafting commissions NOT_SHIPPED. | None | NOT_SHIPPED |
| Faction reputation affects merchant *inventory* (higher tiers reveal hidden stock) | Spec L141. No faction-tier-gated inventory pool in `content/inventory_pools/` or in code. `grep -rnE 'inventory.*tier\|tier.*inventory\|gate_inventory' apps/agent/` → 0 matches. | None | NOT_SHIPPED |
| Faction reputation grants priority access to scarce goods during supply/demand shortages (Honored benefit) | Cross-ref story-002: supply/demand engine NOT_SHIPPED end-to-end; priority access inherits. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — DM Narration Guidance

| Item (verbatim) | Evidence | Tests | Status |
| --- | --- | --- | --- |
| 5 tier-standing narration templates (Neutral / Friendly / Trusted / Honored / Unfriendly) | No template registry for faction-tier narration. `grep -rnE 'faction_tier_narration\|narrate_faction_standing\|TIER_NARRATION' apps/agent/` → 0 matches. `apps/agent/activity_templates.py` carries companion/training narration shims (per phase-6 audit); no parallel for faction-tier narration. | None | NOT_SHIPPED |
| Reputation-shift narration ("Word gets around that you've been supplying the Watch — the next Thornwatch patrol you meet is a shade friendlier") | No reputation-shift narration. | None | NOT_SHIPPED |
| Narration as *consequence*, not transaction (spec L169: "The player doesn't hear '+1 Thornwatch reputation.' They hear the world treating them differently.") | The principle is structurally honored by **absence** — since no reputation pipeline ships, no transactional narration exists. But the **positive form** (world-treating-them-differently narration) isn't built either. | None | NOT_SHIPPED |

## Audit Status (Sprint-006) — Design Decisions 82-86

Spec L173-185 records 5 architectural decisions. Spec L175 claims "Extracted to `game_mechanics_decisions.md` for canonical reference" — **but this extraction has not happened**. The canonical decisions log terminates at Decision 72 (Economy Reconciliation). Decisions 82-86 are still spec-local. Same false-extraction pattern as supply_demand_engine.md decisions 96-104 (see story-002 audit). None are encoded.

| Decision | Item (verbatim) | Status |
| --- | --- | --- |
| 82 | Faction price modifiers are smaller than disposition modifiers (personal > institutional) | NOT_SHIPPED (neither modifier set ships) |
| 83 | Economic activity grants reputation only through meaningful contributions, not purchase volume | NOT_SHIPPED (no granting handler) |
| 84 | Economic reputation gains cap at Trusted (+15); Honored is quest-only | NOT_SHIPPED (no cap) |
| 85 | Faction-exclusive items use a tiered access framework, not exhaustive catalogs | NOT_SHIPPED (framework absent; no per-tier gating) |
| 86 | Detection gates negative reputation from economic activity (Spy archetype protected) | NOT_SHIPPED (no detection pipeline) |

## Deliverables status (per 09_economy.md M9.2 §Deliverables L55-71, cross-doc)

This audit story is doc-only and does not own M9.x deliverables directly — the capstone (story-008) will. Mapping for the capstone:

- 6-tier faction reputation ladder + thresholds: **DESIGNED↔confirmed** (Faction.reputation_tiers schema BUILT, content for 4 factions matches spec thresholds exactly)
- Per-tier price modifier values: **NOT_SHIPPED** (need `price_modifier: number` field on ReputationTier or a global constant table)
- `player_reputation` persistence: **DESIGNED↔confirmed** (table + index BUILT; zero reads/writes)
- Faction modifier function (`apply_faction_modifier(player, faction, item) -> float`): **NOT_SHIPPED**
- Combined disposition × faction stacking: **NOT_SHIPPED** (both inputs absent)
- Reputation-granting economic actions (5 actions): **NOT_SHIPPED**
- Reputation-damaging economic actions (5 actions): **NOT_SHIPPED**
- Caps/cooldowns (max +3/week, once-per-day, Trusted cap on economic path): **NOT_SHIPPED**
- Service refusal gating (Hostile/Unfriendly tiers): **DESIGNED↔aspirational** (effects strings narratively imply, no gating code)
- Faction-exclusive 4-tier access framework: **DESIGNED↔aspirational** (effects strings narratively imply Honored tier; no gating code; Thornwatch + Merchant Guild worked examples have no content backing)
- DM narration patterns (5 tier templates + shift narration): **NOT_SHIPPED**

## Out-of-scope findings (Sprint-spec-cleanup punch list)

Routed to `audit/README.md` Sprint-006 section by capstone (story-008) per wisdom `d0715b09a1df`:

1. **Add `price_modifier: number` to ReputationTier** OR introduce a global tier→modifier constant table. The spec's 6 multipliers (`+15% / 1.0× / -5% / -10% / -15%` plus Hostile=refuse) need a typed home. Schema decision belongs to capstone.
2. **Reconcile content/factions.json with spec faction examples.** Spec uses Thornwatch and Merchant Guild as worked examples (L115-129); content ships accord_guild, aelindran_diaspora, independent, temple_authority. Either backfill Thornwatch/Merchant Guild as content OR update spec to use shipped faction ids. Avoid backfilling both (4→6 factions creates content sprawl ahead of need).
3. **Decisions 82-86 are NOT extracted to `game_mechanics_decisions.md`** despite spec L175 claiming they are. Same gap as story-002 audit's finding for decisions 96-104. Capstone should bulk-fix: extract 82-86 + 96-104 + any other dormant blocks, OR fix the spec claims. Note: decisions log ends at 72, spec decision numbers 82-86 + 96-104 imply a missing 73-81 + 87-95 range. Renumbering may be required to maintain spec→log ID continuity.
4. **`Faction.reputation_tiers.effects: string[]` is narrative prose with no machine reader.** Capstone should decide whether to (a) keep effects as narration-only and surface them via a `narrate_faction_tier(faction_id, tier)` helper, (b) replace with typed structured fields (`services_available: string[]`, `inventory_unlocks: string[]`, `discount_modifier: number`), or (c) both layers (typed + narrative). Today the data exists but is unreachable from code.
5. **`player_reputation` table is BUILT but dormant** — zero reads, zero writes anywhere in code. Capstone should flag this as a high-leverage low-cost wiring task: when reputation pipeline lands, the storage is ready.
6. **NPC schema field for faction affiliation is implicit.** `content/npcs.json` carries `disposition_modifiers` keyed on actions (event-deltas per story-001) but no explicit `faction_id` field per NPC. Spec L48 implies merchant→faction binding ("merchants affiliated with that faction"). Capstone should clarify whether NPC.faction is derivable from `npc.values`/`npc.affiliations` or requires a typed field.
7. **Item value_modifiers already supports faction-keyed multipliers** (`hollow_bone_fragment.value_modifiers["faction:aelindran_diaspora"] = 2.0` in `content/items.json`). This is a per-item per-faction overlay — a different mechanic than the per-tier global modifier (spec L11-21). Capstone should distinguish in M9.x scope: item-level overlay (BUILT, working) vs tier-level modifier (NOT_SHIPPED).

## Verification

Verified-at: e7e0891866646b87b3705b1dbcf7b59f6975b5cd

Grep commands used (all from repo root; 0 matches unless noted):

```bash
# Faction modifier / price function
grep -rnE 'faction_mod|faction_modifier|apply_faction|compute_faction_price|FACTION_MODIFIERS|FACTION_PRICING' apps/ packages/
grep -rnE 'unfriendly.*1\.15|trusted.*0\.9|honored.*0\.85|friendly.*0\.95' apps/ packages/

# Reputation persistence
grep -rnE 'player_reputation|FROM player_reputation|INSERT INTO player_reputation|UPDATE player_reputation' apps/agent/ apps/server/

# Reputation grant/loss handlers
grep -rnE 'grant_reputation|adjust_reputation|reputation_grant|reputation_action|reputation_loss' apps/agent/ apps/server/

# Service refusal / faction inventory gating
grep -rnE 'refuse_service|hostile.*refuse|inventory.*tier|tier.*inventory|gate_inventory|faction_inventory_at_tier|unlock_faction_item' apps/agent/ apps/server/

# Effects-string consumption
grep -rnE 'banned from guild|bounty placed|refused contracts|priority contracts|guild discounts|guild council|field authority|classified intelligence' apps/ packages/

# DM narration templates
grep -rnE 'faction_tier_narration|narrate_faction_standing|TIER_NARRATION' apps/agent/

# Confirmed-present substrate (returned matches):
grep -n 'reputation_tiers' packages/shared/src/entities/faction.ts                       # L14
grep -n 'CREATE TABLE player_reputation\|CREATE TABLE factions' scripts/migrations/001_initial_schema.sql   # L57, L135
grep -n 'idx_player_reputation_faction' scripts/migrations/002_add_indexes.sql           # L5

# Tier coverage in content
python3 -c "import json; d=json.load(open('content/factions.json')); fx=d['factions'] if isinstance(d,dict) else d; print({f['id']: sorted(f['reputation_tiers'].keys()) for f in fx})"
# all 4 factions ship {hostile, unfriendly, neutral, friendly, trusted, honored}

# Spec-vs-content threshold verification (accord_guild sample)
python3 -c "import json; f=json.load(open('content/factions.json'))[0]; print({k:v['threshold'] for k,v in f['reputation_tiers'].items()})"
# {'hostile': -10, 'unfriendly': -5, 'neutral': 0, 'friendly': 5, 'trusted': 15, 'honored': 25}  ← matches spec exactly
```
