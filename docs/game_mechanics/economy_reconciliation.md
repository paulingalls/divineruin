# Divine Ruin — Economy Reconciliation

> **Purpose:** Cross-check every price defined in the mechanics docs against the economy anchor (1 sp = a day's unskilled labor). Identify discrepancies, notation errors, and balance issues. Propose fixes.

---

## Anchor Definition

**1 sp = 1 day's unskilled labor.** This is the canonical reference point from `economy_design.md`.

Derived benchmarks:
- 1 cp = 1/10th of a day's labor (~1 hour of unskilled work)
- 1 gc = 10 sp = 10 days' labor (~2 weeks of unskilled work)
- Unskilled laborer: 1 sp/day = 7 sp/week = ~30 sp/month
- Skilled laborer: ~1.5 sp/day = ~10 sp/week = ~45 sp/month
- Expert craftsman: ~2-3 sp/day = ~15-20 sp/week = ~70 sp/month

---

## RESOLVED: Currency Notation Inconsistency

> **Status:** All fixes applied. See Decision 72 in `game_mechanics_decisions.md`.

### What Was Fixed

Four items used **"gp"** (gold pieces) — a denomination that doesn't exist in the currency system. All were changed to **"gc"** (gold crowns):

| Item | Was | Now | Location Fixed |
|---|---|---|---|
| Half Plate armor | 50 gp | 50 gc | `game_mechanics_magic.md` |
| Plate armor | 100 gp | 100 gc | `game_mechanics_magic.md` |
| Revivify diamond | 50 gp | 50 gc | `game_mechanics_magic.md` |
| Resurrection diamond | 500 gp | 500 gc | `game_mechanics_magic.md` |

The GDD currency ratio was corrected from **1 gc = 100 sp** to **1 gc = 10 sp**, matching the lore bible (10 Marks = 1 Sun). Clean decimal system: 10 cp = 1 sp, 10 sp = 1 gc.

All prices validated under the corrected ratio:

| Item | Price | In Silver | In Days' Labor | Assessment |
|---|---|---|---|---|
| Half Plate | 50 gc | 500 sp | ~500 days (~1.4 years) | **Correct.** Rare military armor, extraordinarily expensive |
| Plate | 100 gc | 1,000 sp | ~1,000 days (~2.7 years) | **Correct.** Most expensive mundane item |
| Revivify diamond | 50 gc | 500 sp | ~500 days | **Correct.** Rare gemstone consumed to cheat death |
| Resurrection diamond | 500 gc | 5,000 sp | ~5,000 days (~14 years) | **Correct but steep.** Intentionally prohibitive — Mortaen's domain is the normal path |

---

## Price Validation: All Items Against Anchor

### Food & Lodging

| Item | Price | Days' Labor | Assessment |
|---|---|---|---|
| Rations (1 day) | 5 cp | 0.5 days | **Good.** Food costs half a day's wage — leaves room for other expenses |
| Waterskin | 2 cp | 0.2 days | **Good.** Basic container, trivially cheap |
| Common room lodging | 1 sp / night | 1 day | **Slightly high.** A laborer's entire daily wage for a crowded room feels steep. Consider 5 cp (half a day's wage) for a common room. But defensible in a war economy with refugee pressure on housing |
| Private room | 5 sp / night | 5 days | **Good.** Moderate luxury, accessible to skilled laborers and adventurers |
| Fine room | 15 sp / night | 15 days | **Good.** Real luxury, two weeks' wages. Appropriate for the quality bonus it grants |

### Basic Weapons

| Item | Price | Days' Labor | Assessment |
|---|---|---|---|
| Spear | 1 sp | 1 day | **Good.** A stick with a point — the cheapest real weapon |
| Dagger | 2 sp | 2 days | **Good.** Small blade, minimal metalwork |
| Staff | 2 sp | 2 days | **Good.** Shaped wood |
| Handaxe | 2 sp | 2 days | **Good.** Simple metal head |
| Mace | 3 sp | 3 days | **Good.** More metal, more work |
| Short Sword | 5 sp | 5 days | **Good.** A week's wages for a proper blade |
| Battleaxe | 8 sp | 8 days | **Good.** Heavier metalwork |
| Longsword | 10 sp | 10 days | **Good.** The standard warrior's weapon costs a week and a half |
| Warhammer | 10 sp | 10 days | **Good.** Same bracket as longsword |
| Rapier | 15 sp | 15 days | **Good.** Precision weapon, more expensive to forge |
| Shortbow | 15 sp | 15 days | **Good.** Crafted ranged weapon |
| Light Crossbow | 15 sp | 15 days | **Good.** Mechanical weapon |
| Greatsword | 25 sp | 25 days | **Good.** Nearly a month — serious weapon, serious cost |
| Longbow | 30 sp | 30 days | **Good.** A month's wages for a quality ranged weapon |
| Heavy Crossbow | 30 sp | 30 days | **Good.** Same bracket as longbow |
| Hand Crossbow | 40 sp | 40 days | **Good.** Most expensive standard weapon — compact, specialized |

**Weapon range: 1-40 sp.** Clean progression from simple (1-3 sp) to martial (5-15 sp) to specialized (25-40 sp). No issues.

### Armor

| Item | Price | Days' Labor | Assessment |
|---|---|---|---|
| Padded | 3 sp | 3 days | **Good.** Cheapest real armor |
| Leather | 5 sp | 5 days | **Good.** A week's wages |
| Hide | 5 sp | 5 days | **Good.** Same bracket as leather |
| Shield | 5 sp | 5 days | **Good.** Wood and metal |
| Studded Leather | 25 sp | 25 days | **Good.** Nearly a month — significant upgrade from basic leather |
| Chain Shirt | 30 sp | 30 days | **Good.** A month for metal armor. The entry point for medium armor |
| Scale Mail | 30 sp | 30 days | **Good.** Same bracket as chain shirt |
| Chain Mail | 50 sp | 50 days | **Good.** Nearly two months. Serious heavy armor |
| Half Plate | 50 gc | 500 days | **Good (with gc = 10 sp fix).** Rare military hardware, over a year's wages |
| Plate | 100 gc | 1,000 days | **Good (with gc = 10 sp fix).** The most expensive mundane item. Nearly 3 years' labor |

**Armor range: 3 sp to 100 gc.** Clean progression with a dramatic jump from Chain Mail (50 sp) to Half Plate (500 sp). This jump is intentional — Half Plate and Plate are Rare items, not purchasable in most shops. They represent master-crafted military equipment.

### Adventuring Gear

| Item | Price | Days' Labor | Assessment |
|---|---|---|---|
| Torch | 1 cp | 0.1 days | **Good.** Trivially cheap disposable |
| Oil Flask | 1 cp | 0.1 days | **Good.** Cheap fuel |
| Rope (50 ft) | 1 sp | 1 day | **Good.** Basic utility item |
| Bedroll | 1 sp | 1 day | **Good.** Essential travel gear |
| Backpack | 2 sp | 2 days | **Good.** Container |
| Grappling Hook | 2 sp | 2 days | **Good.** Simple metal hook |
| Tent (2 person) | 2 sp | 2 days | **Slightly cheap.** A tent for 2 days' wages feels like a deal. Consider 5 sp. But a basic canvas shelter could be this cheap |
| Crystal Flask | 3 sp | 3 days | **Good.** Specialty item for potion crafting |
| Healer's Kit | 5 sp | 5 days | **Good.** Consumable medical supplies |
| Holy Symbol | 5 sp | 5 days | **Good.** Crafted religious item |
| Ink & Quill | 5 sp | 5 days | **Good.** Specialty writing supplies |
| Lantern | 5 sp | 5 days | **Good.** Metal and glass — significant purchase for a laborer |
| Arcane Focus | 10 sp | 10 days | **Good.** Magical tool |
| Thieves' Tools | 15 sp | 15 days | **Good.** Specialized precision instruments |
| Climbing Kit | 15 sp | 15 days | **Good.** Professional equipment |

**Adventuring gear range: 1 cp to 15 sp.** All reasonable against anchor.

### NPC Services

| Service | Price | Days' Labor | Assessment |
|---|---|---|---|
| Heal Wounds (1d8+WIS) | 5 sp | 5 days | **Good.** Magical healing is valuable — a week's wages for a wound closed |
| Cure Poison/Disease | 15 sp | 15 days | **Good.** Two weeks' wages for condition removal |
| Dispel Corruption | 25 sp | 25 days | **Good.** Specialized anti-Hollow service. Nearly a month's wages |
| Remove Curse | 50 sp | 50 days | **Good.** Rare service, nearly two months' wages |
| Greater Restoration | 200 sp | 200 days | **Good.** Over 6 months' wages. Major divine magic |
| Resurrection (NPC service) | 1,000+ sp | 1,000+ days | **Good.** ~3 years' wages. Intentionally prohibitive. Mortaen's domain is the normal path |
| Identify item | 10 sp | 10 days | **Good.** Scholarly service |
| Identify Hollow material | 25 sp | 25 days | **Good.** Specialized and dangerous |
| Research (common) | 15 sp | 15 days | **Good.** Days of a scholar's time |
| Research (obscure) | 50 sp | 50 days | **Good.** Extended research project |
| Translate text | 25 sp | 25 days | **Good.** Rare linguistic skill |

**Service range: 5-1000+ sp.** Clean progression from basic (5-15 sp) to specialized (25-50 sp) to extraordinary (200-1000+ sp).

### Workspace Rental

| Workspace | Price | Days' Labor | Assessment |
|---|---|---|---|
| Workshop | 2 sp / day | 2 days' wages per day of use | **Good.** You're paying for tools and space beyond your own labor value |
| Forge | 5 sp / day | 5 days | **Good.** Expensive equipment, fuel costs, specialized space |
| Laboratory | 10 sp / day | 10 days | **Good.** Alchemical equipment is expensive. A week and a half's wages per day of use |
| Forge + Laboratory | 12 sp / day | 12 days | **Good.** Slight discount over separate rental |

**Note:** Disposition discount (Friendly: 80%, Trusted: 60%) brings these down significantly. Trusted Forge = 3 sp/day. Standing access = free.

### Crafting Commissions (NPC Blacksmith)

| Tier | Materials Provided | Smith Provides | Assessment |
|---|---|---|---|
| 1 | 5 sp | 15 sp | **Good.** Labor cost (5 sp) is a week's wages. With materials (15 sp) includes material markup |
| 2 | 25 sp | 75 sp | **Good.** Nearly a month for expert work. 75 sp with materials is over two months — reflects expensive components |
| 3 | 100 sp | 300+ sp | **Good.** Over 3 months for master work. 300 sp is nearly a year — this is a serious commission |

### Repair Pricing (NPC Blacksmith)

| Item Tier | Cost | Assessment |
|---|---|---|
| Common | 2 sp | **Good.** A couple days' wages for basic repair |
| Uncommon | 10 sp | **Good.** A week and a half |
| Rare | 50 sp | **Good.** Nearly two months — rare items require rare skill |
| Legendary | 200+ sp | **Good.** Over 6 months. Legendary items are one-of-a-kind |

### Mentor Training Fees

| Range | Examples | Assessment |
|---|---|---|
| 15-20 sp | Frontier exiles, informal mentors | **Good.** 2-3 weeks' wages for informal training |
| 25-40 sp | Standard military/guild mentors | **Good.** 1-1.5 months. A real investment |
| 50-75 sp | Elite/specialized mentors | **Good.** 2-2.5 months. Serious commitment |
| 80-100 sp | Legendary/master mentors | **Good.** 3+ months. The best training costs the most |
| 0 sp (Kael Thornridge) | Honor-based, quest-gated | **Good.** The most powerful variant costs nothing in gold — the cost is the quest |

### Starting Gold

| Category | Starting Gold | Assessment |
|---|---|---|
| Most archetypes | 10 sp | **Good.** 10 days' labor. Enough for a few nights at an inn (5-15 sp), a meal or two (5-10 cp), and basic supplies. Tight but functional — players need to earn more quickly |
| Diplomat | 15 sp | **Good.** 50% premium reflects the Diplomat's social resources |

**Starting wealth buys:** ~2 nights at a private room (10 sp) + 2 days rations (10 cp) + nothing left. Or: ~10 nights at a common room (10 sp) + 10 days rations (50 cp) + 5 sp remaining. The economy creates immediate pressure to earn — which is good. Quest rewards are the primary income source.

### Spell Component Costs

| Component | Price | In Silver | Assessment |
|---|---|---|---|
| Revivify diamond | 50 gc | 500 sp | **Good (with fix).** Over a year's labor. Death-prevention should cost a fortune |
| Resurrection diamond | 500 gc | 5,000 sp | **Good (with fix).** ~14 years' labor. Intentionally near-impossible for individuals. This is "sell everything you own" territory, or "the temple funds it" territory |

### Hollow Material Values (Scholar purchases)

| Material | Price Range | Assessment |
|---|---|---|
| Hollow research samples | 50-500 sp | **Good.** Tier-dependent. Scholars pay premium for rare materials. A Named fragment at 500 sp is over a year's wages — but Named creatures are endgame content |

---

## Summary

### Resolved

1. ~~**"gp" notation**~~ — All 4 instances changed to "gc". GDD ratio corrected to 1 gc = 10 sp. ✅

### Minor (accepted as-is)

2. **Common room at 1 sp/night** — Full day's labor for a crowded room. Accepted: common rooms are for adventurers, not laborers. Laborers sleep at home.

3. **Tent at 2 sp** — Cheap for a shelter, but defensible for basic canvas.

### No Issues

Everything else validates cleanly against the anchor. Weapons scale 1-40 sp, armor 3 sp to 100 gc, services 5-1000+ sp. Each tier is proportionate to labor cost. War economy context justifies slightly elevated military equipment prices.
