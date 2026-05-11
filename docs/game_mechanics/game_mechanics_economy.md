# Divine Ruin — Economy & Pricing Reference

> **Purpose:** Canonical economy specification and pricing reference. This document holds the *static* economic data — currency definitions, the economic anchor, and the canonical price tables. The *dynamic* economic systems (faction pricing modifiers, merchant inventory mechanics, supply and demand, gold sinks, inflation control, player-to-player trade) live in dedicated subsystem documents under `economy/`.
>
> **All prices validated against the economy anchor** (1 sp = 1 day's unskilled labor). Source of truth for Phase 9 implementation.

---

## Subsystem Documents

This document is the canonical pricing reference. The mechanical systems that operate on top of these prices are documented separately:

| Document | Purpose |
|---|---|
| [`economy/faction_reputation_pricing.md`](economy/faction_reputation_pricing.md) | Faction reputation modifiers, faction-exclusive access, reputation through economic activity |
| [`economy/merchant_inventory_restock.md`](economy/merchant_inventory_restock.md) | Three-tier stock model, inventory pool definitions, daily restock mechanics, merchant gold pools |
| [`economy/supply_demand_engine.md`](economy/supply_demand_engine.md) | Event-driven price fluctuation, three-phase event lifecycle, standard economic event catalog |
| [`economy/gold_sink_ledger.md`](economy/gold_sink_ledger.md) | Consolidated ledger of all gold sinks, magnitude analysis, gap analysis, sink design philosophy |
| [`economy/inflation_targets_controls.md`](economy/inflation_targets_controls.md) | Wealth-by-level curves, faucet/sink ratio targets, god-agent economic intervention, seasonal events |
| [`economy/game_mechanics_p2p_trade.md`](economy/game_mechanics_p2p_trade.md) | Phase 2+ player-to-player trade design intent, inherited constraints, open questions |

The encounter role system, which governs creature loot scaling and is referenced from the economy, is documented in [`game_mechanics_encounter_roles.md`](game_mechanics_encounter_roles.md) (top-level mechanics doc, not economy-specific).

---

## Currency System

Three-tier decimal currency:

- **Copper pieces (cp)** — 10 cp = 1 sp. Pocket change. A meal, a drink, a night at a cheap inn.
- **Silver pieces (sp)** — The baseline. A good weapon, a day's skilled labor, a useful potion.
- **Gold crowns (gc)** — 1 gc = 10 sp. Significant wealth. Property, rare items, major services.

All notation uses **cp**, **sp**, and **gc**. The denomination "gp" (gold pieces) does not exist in Aethos.

## Economic Anchor

**1 sp = 1 day's unskilled labor.** This is the canonical reference point for all pricing.

Derived benchmarks:
- 1 cp = 1/10th of a day's labor (~1 hour of unskilled work)
- 1 gc = 10 sp = 10 days' labor (~2 weeks of unskilled work)
- Unskilled laborer: 1 sp/day = 7 sp/week = ~30 sp/month
- Skilled laborer: ~1.5 sp/day = ~10 sp/week = ~45 sp/month
- Expert craftsman: ~2-3 sp/day = ~15-20 sp/week = ~70 sp/month

---

## Canonical Price Tables

### Food & Lodging

| Item | Price | Days' Labor |
|---|---|---|
| Rations (1 day) | 5 cp | 0.5 |
| Waterskin | 2 cp | 0.2 |
| Common room lodging | 1 sp / night | 1 |
| Private room | 5 sp / night | 5 |
| Fine room | 15 sp / night | 15 |

### Weapons

| Item | Price | Days' Labor |
|---|---|---|
| Spear | 1 sp | 1 |
| Dagger | 2 sp | 2 |
| Staff | 2 sp | 2 |
| Handaxe | 2 sp | 2 |
| Mace | 3 sp | 3 |
| Short Sword | 5 sp | 5 |
| Battleaxe | 8 sp | 8 |
| Longsword | 10 sp | 10 |
| Warhammer | 10 sp | 10 |
| Rapier | 15 sp | 15 |
| Shortbow | 15 sp | 15 |
| Light Crossbow | 15 sp | 15 |
| Greatsword | 25 sp | 25 |
| Longbow | 30 sp | 30 |
| Heavy Crossbow | 30 sp | 30 |
| Hand Crossbow | 40 sp | 40 |

**Range: 1-40 sp.** Simple (1-3 sp) → martial (5-15 sp) → specialized (25-40 sp).

### Armor

| Item | Price | Days' Labor |
|---|---|---|
| Padded | 3 sp | 3 |
| Leather | 5 sp | 5 |
| Hide | 5 sp | 5 |
| Shield | 5 sp | 5 |
| Studded Leather | 25 sp | 25 |
| Chain Shirt | 30 sp | 30 |
| Scale Mail | 30 sp | 30 |
| Chain Mail | 50 sp | 50 |
| Half Plate | 50 gc | 500 |
| Plate | 100 gc | 1,000 |

**Range: 3 sp to 100 gc.** Dramatic jump from Chain Mail (50 sp) to Half Plate (500 sp) is intentional — Half Plate and Plate are Rare military equipment.

### Adventuring Gear

| Item | Price | Days' Labor |
|---|---|---|
| Torch | 1 cp | 0.1 |
| Oil Flask | 1 cp | 0.1 |
| Rope (50 ft) | 1 sp | 1 |
| Bedroll | 1 sp | 1 |
| Backpack | 2 sp | 2 |
| Grappling Hook | 2 sp | 2 |
| Tent (2 person) | 2 sp | 2 |
| Crystal Flask | 3 sp | 3 |
| Healer's Kit | 5 sp | 5 |
| Holy Symbol | 5 sp | 5 |
| Ink & Quill | 5 sp | 5 |
| Lantern | 5 sp | 5 |
| Arcane Focus | 10 sp | 10 |
| Thieves' Tools | 15 sp | 15 |
| Climbing Kit | 15 sp | 15 |

**Range: 1 cp to 15 sp.**

### Spell Components

| Component | Price | In Silver |
|---|---|---|
| Revivify diamond | 50 gc | 500 sp |
| Resurrection diamond | 500 gc | 5,000 sp |

---

## NPC Services

| Service | Price | Days' Labor |
|---|---|---|
| Heal Wounds (1d8+WIS) | 5 sp | 5 |
| Cure Poison/Disease | 15 sp | 15 |
| Dispel Corruption | 25 sp | 25 |
| Remove Curse | 50 sp | 50 |
| Greater Restoration | 200 sp | 200 |
| Resurrection (NPC service) | 1,000+ sp | 1,000+ |
| Identify item | 10 sp | 10 |
| Identify Hollow material | 25 sp | 25 |
| Research (common) | 15 sp | 15 |
| Research (obscure) | 50 sp | 50 |
| Translate text | 25 sp | 25 |

**Range: 5-1,000+ sp.** Basic (5-15 sp) → specialized (25-50 sp) → extraordinary (200-1,000+ sp).

---

## Workspace Rental

| Workspace | Price |
|---|---|
| Workshop | 2 sp / day |
| Forge | 5 sp / day |
| Laboratory | 10 sp / day |
| Forge + Laboratory | 12 sp / day |

**Disposition discounts:** Friendly pays 80%, Trusted pays 60%. Standing access (via quest/relationship) = free.

---

## Crafting Commissions (NPC Blacksmith)

| Tier | Player Provides Materials | Smith Provides All |
|---|---|---|
| 1 | 5 sp | 15 sp |
| 2 | 25 sp | 75 sp |
| 3 | 100 sp | 300+ sp |

### Repair Pricing

| Item Tier | Cost |
|---|---|
| Common | 2 sp |
| Uncommon | 10 sp |
| Rare | 50 sp |
| Legendary | 200+ sp |

---

## Mentor Training Fees

| Range | Examples |
|---|---|
| 15-20 sp | Frontier exiles, informal mentors |
| 25-40 sp | Standard military/guild mentors |
| 50-75 sp | Elite/specialized mentors |
| 80-100 sp | Legendary/master mentors |
| 0 sp | Honor-based, quest-gated (e.g., Kael Thornridge) |

---

## Starting Gold

| Category | Starting Gold |
|---|---|
| Most archetypes | 10 sp |
| Diplomat | 15 sp |

Starting wealth creates immediate pressure to earn. 10 sp buys ~10 nights common room + 10 days rations + 5 sp remaining, or ~2 nights private room + 2 days rations + nothing left.

---

## Merchant Pricing Formula

The price a merchant offers is the product of multiple modifiers applied to the item's base price:

```
final_price = base_price × disposition_modifier × faction_modifier × event_modifier × context_modifier
final_price = clamp(final_price, base_price × 0.5, base_price × 3.0)
```

### Disposition Modifiers

| Disposition | Price Modifier |
|---|---|
| Hostile | +20% |
| Unfriendly | +10% |
| Neutral | 1.0× (base price) |
| Friendly | -10% |
| Trusted | -20% |

### Other Modifiers

The remaining modifiers — faction reputation, world events, regional context — and the price clamp bounds are documented in their respective subsystem docs:

- **Faction reputation modifiers** → see [`economy/faction_reputation_pricing.md`](economy/faction_reputation_pricing.md)
- **Event-driven modifiers** (Hollow incursions, plagues, festivals, etc.) → see [`economy/supply_demand_engine.md`](economy/supply_demand_engine.md)
- **Regional/contextual modifiers** (item-specific `value_modifiers` in entity data) → see `world_data_simulation.md`

The 0.5×–3.0× clamp is a hard bound on the final computed price after all modifiers stack. Rationale and stacking rules are documented in [`economy/supply_demand_engine.md`](economy/supply_demand_engine.md).

---

## Quest Reward Tiers

| Tier | Reward Range | Typical Content |
|---|---|---|
| 1 | 25-50 sp | Early-game quests, simple tasks |
| 2 | 100-250 sp | Mid-game quests, moderate danger |
| 3 | 300-700 sp | Late-game quests, significant challenge |

Quest rewards are the primary economic faucet. Per-session balance targets and faucet/sink ratios are documented in [`economy/inflation_targets_controls.md`](economy/inflation_targets_controls.md). XP-to-reward correlation, bonus reward conditions, and non-currency rewards (items, reputation, faction standing) are part of the broader progression system and remain to be specified.

---

## Hollow Material Values

| Material | Price Range |
|---|---|
| Hollow research samples (Drift residue) | 5-15 sp |
| Hollow research samples (Rend tier) | 50-100 sp |
| Hollow research samples (Wrack tier) | 200-500 sp |
| Named creature fragments | 500 sp (fixed) |

Tier-dependent. Scholars pay premium for rare materials. Named creature fragments at 500 sp represent endgame content.

For the complete material sell value framework (hides, bones, venom, fiber, arcane components, divine materials by creature tier), see [`game_mechanics_encounter_roles.md`](game_mechanics_encounter_roles.md) — Material Sell Values section.

---

## Currency Drops from Combat

Currency dropped by defeated creatures is determined by creature category, tier, and encounter role. The full framework is in [`game_mechanics_encounter_roles.md`](game_mechanics_encounter_roles.md). Summary:

- **Beasts and constructs** drop no currency (animals don't carry coin)
- **Humanoids** always drop currency (Tier × 1d6 sp)
- **Hollow (Drift tier)** drop no currency (dissolve into nothing)
- **Hollow (Rend+ tier)** sometimes drop currency (15% chance, absorbed from victims)
- **Undead** sometimes drop currency (25% chance, grave goods)

Currency drops are modified by encounter role (Minions never drop currency; Bosses drop 2× plus a tier-scaled bonus).
