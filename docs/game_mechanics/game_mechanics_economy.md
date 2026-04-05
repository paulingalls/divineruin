# Divine Ruin — Economy & Pricing Reference

> **Purpose:** Canonical economy specification. All prices validated against the economy anchor (1 sp = 1 day's unskilled labor). Source of truth for Phase 9 implementation.

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

### Disposition Modifiers

| Disposition | Price Modifier |
|---|---|
| Hostile | +20% |
| Unfriendly | +10% |
| Neutral | 1.0x (base price) |
| Friendly | -10% |
| Trusted | -20% |

### Faction Reputation Modifier

Stacks multiplicatively with disposition. Higher faction standing with a merchant's faction reduces prices across the board.

*TODO: Define faction reputation tiers and their specific price modifiers.*

---

## Quest Reward Tiers

| Tier | Reward Range | Typical Content |
|---|---|---|
| 1 | 25-50 sp | Early-game quests, simple tasks |
| 2 | 100-250 sp | Mid-game quests, moderate danger |
| 3 | 300-700 sp | Late-game quests, significant challenge |

*TODO: Define XP-to-reward correlation, bonus reward conditions, and non-currency rewards (items, reputation, faction standing).*

---

## Hollow Material Values

| Material | Price Range |
|---|---|
| Hollow research samples | 50-500 sp |

Tier-dependent. Scholars pay premium for rare materials. Named creature fragments at 500 sp represent endgame content.

---

## Systems Not Yet Specified

The following economy systems need mechanical design before Phase 9 implementation. The GDD (`game_design_doc.md` lines 1046-1084) describes the design philosophy for each but lacks mechanical formulas.

### Loot & Drop Tables
- What enemies drop on defeat and at what rates
- Loot quality scaling by enemy tier (Minion → Standard → Elite → Boss → Named)
- Randomization rules: fixed drops vs. loot pools vs. contextual drops
- How the DM narrates loot discovery (audio-first constraint)

### Supply & Demand Engine
- How regional events affect prices (Hollow incursion → healing potion prices rise)
- Formula for price fluctuation based on simulation tick events
- Price floor/ceiling bounds to prevent economy-breaking swings
- How merchant inventory interacts with regional supply state

### Merchant Inventory & Restock
- What each merchant type stocks (weapons dealer vs. general store vs. alchemist)
- Restock timing: per simulation tick? Per real-time day? On visit?
- Inventory limits per merchant tier
- How scarcity is narrated ("Grimjaw's sold out of healing potions — try the next town")

### Player-to-Player Trade
- Direct trade rules (in-person, same location)
- Remote trade / auction house mechanics (if any)
- Trade fees or taxes (faction-controlled markets?)
- Anti-fraud / anti-exploit guardrails

### Faction Reputation Pricing
- Specific faction reputation tiers and their price modifiers
- How faction standing is gained/lost through economic activity
- Faction-exclusive items or services

### Gold Sinks
- Systematic list of where currency permanently leaves the economy
- Property maintenance costs, guild upkeep, consumable costs
- Death costs (Mortaen's domain fees escalate — see `game_mechanics_combat.md`)
- Training and crafting material costs as sinks

### Inflation Controls
- How the world economy stays balanced with thousands of players
- Currency generation rate vs. sink rate targets
- God-agent economic intervention mechanics
- Seasonal economic events and resets
