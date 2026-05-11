# Merchant Inventory & Restock — Economy Section

> **Integration note:** This section replaces the "Merchant Inventory & Restock" stub in `game_mechanics_economy.md` under "Systems Not Yet Specified." Cross-references: `world_data_simulation.md` (simulation tick, `inventory_pools` table, NPC schema), `game_mechanics_npcs.md` (merchant subtypes, settlement templates), `game_mechanics_crafting.md` (item catalogs).

---

## Merchant Inventory & Restock

### Three-Tier Stock Model

Merchant inventory operates in three tiers based on item importance and game-feel impact:

| Tier | Stock Behavior | What Belongs Here | Why |
|---|---|---|---|
| **Tier 1: Always-Stocked** | Effectively infinite. Never depletes | Trivial supplies — rations, torches, oil flasks, basic ammunition, rope, common food | Running out of torches in the village creates frustration without interesting choices. The friction isn't worth the gameplay |
| **Tier 2: Limited Stock** | Finite quantity, depletes when sold, refills on daily restock | Quality goods — weapons, armor, potions, kits, reagents, tools | This is where scarcity creates meaningful choices. Can run out, must wait or travel for more |
| **Tier 3: Unique/Rare** | Single instance. May not restock, or restocks only weekly | Specific masterwork items, rare components, one-off magical items, exotic imports | Creates "I have to come back for that" moments. Generates pull toward specific merchants |

The three-tier model balances frictionless basics with meaningful scarcity. A player can always replenish torches at any village; they cannot always find healing potions on demand.

---

### Inventory Pools — Definitions

Inventory pools are content data stored in the `inventory_pools` PostgreSQL table. Each pool defines a weighted distribution of items that may appear at merchants drawing from that pool. Specific stock at a given merchant is determined by:

1. The pool the merchant draws from (per their NPC schema)
2. The settlement's size and personality (determines pool tier and quantity)
3. Current world state (regional events may alter availability)

#### Pool: `general_supplies`

**Drawn from by:** General Goods merchants in any settlement.

**Always-Stocked (Tier 1):**

| Item | Notes |
|---|---|
| Rations (1 day) | 5 cp each |
| Waterskin | 2 cp each |
| Torch | 1 cp each |
| Oil Flask | 1 cp each |
| Rope (50 ft) | 1 sp each |
| Bedroll | 1 sp each |
| Sack / Backpack | 2 sp each |

**Limited Stock (Tier 2) — varies by settlement size:**

| Item | Hamlet | Village | Town | City |
|---|---|---|---|---|
| Healer's Kit | 0 | 1 | 2 | 4 |
| Lantern | 0 | 1 | 2 | 4 |
| Tent (2-person) | 0 | 1 | 2 | 3 |
| Grappling Hook | 0 | 0-1 | 1-2 | 2-4 |
| Climbing Kit | 0 | 0 | 0-1 | 1-2 |
| Ink & Quill | 0 | 0 | 0-1 | 1-2 |
| Holy Symbol (basic) | 0 | 0-1 | 1 | 2-3 |
| Crystal Flask | 0 | 0 | 0-1 | 1-2 |

#### Pool: `weapons_armor_basic`

**Drawn from by:** Weapons & Armor merchants in villages and small towns. Most blacksmiths.

**Limited Stock (Tier 2):**

| Item | Hamlet | Village | Town | City |
|---|---|---|---|---|
| Spear | — | 1-3 | 2-5 | 3-8 |
| Dagger | — | 1-2 | 2-4 | 3-6 |
| Handaxe | — | 1-2 | 2-3 | 3-5 |
| Mace | — | 0-1 | 1-2 | 2-4 |
| Short Sword | — | 0-1 | 1-2 | 2-3 |
| Battleaxe | — | 0 | 0-1 | 1-2 |
| Longsword | — | 0 | 0-1 | 1-2 |
| Shortbow | — | 0-1 | 1 | 2-3 |
| Light Crossbow | — | 0 | 0-1 | 1-2 |
| Padded Armor | — | 0-1 | 1-2 | 2-3 |
| Leather Armor | — | 0-1 | 1-2 | 2-3 |
| Hide Armor | — | 0-1 | 1 | 1-2 |
| Shield | — | 1-2 | 2-3 | 3-4 |

**Hamlets do not stock weapons or armor.** Hamlets that need weapons trade through visiting merchants or travel to the nearest village.

#### Pool: `weapons_armor_quality`

**Drawn from by:** Weapons & Armor merchants in towns and cities. Master blacksmiths.

**Limited Stock (Tier 2):**

| Item | Town | City |
|---|---|---|
| Rapier | 0-1 | 1-2 |
| Greatsword | 0-1 | 1-2 |
| Warhammer | 0-1 | 1-2 |
| Longbow | 0-1 | 1-2 |
| Heavy Crossbow | 0 | 0-1 |
| Hand Crossbow | 0 | 0-1 |
| Studded Leather | 0-1 | 1-2 |
| Chain Shirt | 0-1 | 1-2 |
| Scale Mail | 0 | 0-1 |
| Chain Mail | 0 | 0-1 |

**Unique/Rare (Tier 3) — cities only:**

| Item | Availability | Restock |
|---|---|---|
| Half Plate | 25% chance present at any given time | Weekly check |
| Plate | 10% chance present at any given time | Weekly check |
| Quality / masterwork variant of any standard weapon (+1 damage, "well-balanced") | One per merchant, rotates | Restocks 1 per real-week if sold |

#### Pool: `alchemical_supplies_common`

**Drawn from by:** Alchemists in towns and cities. Some general merchants in cities.

**Always-Stocked (Tier 1):**

| Item | Notes |
|---|---|
| Crystal Flask | 3 sp each (potion crafting equipment) |
| Common herbs / dried reagents | 1 sp per bundle, narrative description |

**Limited Stock (Tier 2):**

| Item | Town | City |
|---|---|---|
| Minor Healing Potion (2d4+2 HP) | 1-3 | 3-6 |
| Antitoxin (advantage on poison saves, 1 hour) | 0-1 | 1-2 |
| Smelling salts (remove unconscious from 0 HP, single-use) | 1-2 | 2-4 |
| Common reagents (alchemy materials) | 2-4 | 4-8 |

**Unique/Rare (Tier 3):**

| Item | Availability | Restock |
|---|---|---|
| Greater Healing Potion (4d4+4 HP) | Cities only, 50% chance present | Daily restock check |
| Specialty antidotes (Hollow toxin, Mawling venom) | Border towns and cities, 25% chance | Weekly check |
| Custom-mixed potions | Commission-only, requires Expert Alchemist | Made on demand, 1-3 days |

#### Pool: `exotic_goods`

**Drawn from by:** Exotic Goods merchants in cities and major trade routes.

**Limited Stock (Tier 2):**

| Item | City |
|---|---|
| Imported food / spices | 3-6 |
| Foreign cultural goods | 2-4 |
| Purified Hollow materials (research-grade) | 1-3 |
| Rare crafting reagents | 1-2 |

**Unique/Rare (Tier 3):**

| Item | Availability | Notes |
|---|---|---|
| Rotating "feature item" — varies by merchant | 1 unique item per merchant at any time | Restocks 1 per real-week. Examples: a ceremonial blade from the Drathian Steppe, a Keldaran mining tool, an Aelindran star-chart, a sealed reliquary from a destroyed temple |

#### Pool: `jeweler_goods`

**Drawn from by:** Jewelers in cities only.

**Limited Stock (Tier 2):**

| Item | City |
|---|---|
| Common gems (10-25 sp value) | 5-10 |
| Quality gems (50-100 sp value) | 2-4 |
| Jewelry (rings, pendants, brooches) | 4-8 |

**Unique/Rare (Tier 3):**

| Item | Availability |
|---|---|
| Rare gems (200+ sp) | 0-1, 30% chance present |
| Enchanted trinkets (minor magical effects) | 0-1, 15% chance present |

#### Pool: `black_market`

**Drawn from by:** Black Market dealers in cities (hidden) and certain taverns. Requires disposition Trusted to access full inventory.

**Limited Stock (Tier 2) — visible at Friendly:**

| Item | Notes |
|---|---|
| Stolen weapons (-25% price, faction reputation risk if caught carrying) | 1-3 |
| Restricted poisons | 0-2 |
| Smuggled goods (untaxed alchemy, foreign restricted items) | 2-4 |

**Unique/Rare (Tier 3) — visible at Trusted:**

| Item | Notes |
|---|---|
| Tainted Hollow materials (unpurified, illegal) | 1-2 |
| Forged documents (faction credentials, trade permits) | 0-1 |
| Faction-restricted items (Thornwatch gear sold to outsiders, Ashmark intelligence reports) | 0-1 |

**Black market mechanics:**
- All purchases here carry risk of detection (Insight checks by faction NPCs in subsequent interactions)
- Faction reputation loss applies when detected (see Faction Reputation Pricing)
- The black market merchant won't accept high-disposition Thornwatch or Ashmark agents as customers (they refuse service to faction loyalists)

---

### Stock Limits by Settlement

The quantity ranges shown in pool tables are *base ranges*. Actual stock at a given merchant is determined by settlement size, personality, and current world state.

#### Settlement Size Multipliers

| Settlement | Tier 1 Pool Access | Tier 2 Stock Multiplier | Tier 3 Pool Access |
|---|---|---|---|
| Hamlet | Limited (basics only) | 0.25× | None |
| Village | Yes | 0.5× | None |
| Town | Yes | 1.0× (baseline) | Limited (1-2 items) |
| City | Yes | 1.5× | Yes (full Tier 3 pools) |
| Capital | Yes | 2.0× | Yes + capital-exclusive pools |

#### Settlement Personality Modifiers

Personality traits stack on top of size multipliers:

| Trait | Effect on Inventory |
|---|---|
| **Prosperous** | +25% stock across all tiers. Tier 3 chance increased by +15%. Higher-quality variants more common |
| **Struggling** | -50% stock. No Tier 3 inventory. Some Tier 2 items unavailable (DM narrates as "we don't have any of those right now") |
| **Military** | Weapons/armor stock +50%. Civilian goods (jewelry, exotic, alchemy) -25%. Faction (Ashmark/Thornwatch) merchants get priority restock |
| **Trade Hub** | All pools +25%. Traveling merchants more frequent. Black market presence guaranteed |
| **Isolated** | -50% Tier 2 stock. No Tier 3. Traveling merchants rare. Items 25% more expensive (supply chain costs) |
| **Cursed/Corrupted** | -75% stock. Most merchants have left or refuse to deal. What remains is desperate trade |

**Example application:** A Prosperous Town with `weapons_armor_basic` pool draws baseline town stock (1-2 longswords), adds +25% (rounds up to 2-3 longswords), and the merchant is more likely to have a quality variant.

**Example application:** A Struggling Village with `general_supplies` pool draws baseline village stock at 0.5× (so 0-1 healer's kit becomes 0), removes Tier 3 access, and the DM narrates the empty shelves: "Grimjaw's stall is half-empty. He apologizes — supply lines from the city haven't come through this month."

---

### Daily Restock Mechanics

Inventory restocks once per in-game day, at dawn (06:00 in-game time). The simulation tick layer 1 (time-driven) handles this.

#### Restock Process

```
At dawn each in-game day:
  For each merchant in the world:
    For each Tier 2 item in their inventory pool:
      Roll against the item's quantity range
      Set merchant's current stock to the rolled quantity
    For each Tier 3 item in their pool:
      Roll against the item's "chance present" probability
      If present: stock = 1
      If item was sold yesterday and is rotation-based: skip restock until weekly tick
    
  For each merchant's gold pool:
    Reset to merchant's daily gold allocation
    (See Merchant Gold Pool below)
```

#### Restock Frequency by Tier

| Stock Tier | Restock Frequency | Notes |
|---|---|---|
| Tier 1 (Always-Stocked) | Continuous | Never depletes, no restock needed |
| Tier 2 (Limited) | Daily (at dawn) | Quantity rolled fresh each day |
| Tier 3 (Unique/Rare) | Daily probability check OR weekly rotation | Depending on item type. Rotating "feature items" use weekly tick |

#### Restock Disruption

Restock can be modified or blocked by world events:

- **Trade route disrupted (Hollow incursion, bandit activity):** Affected settlements get -50% Tier 2 restock for the duration. Tier 3 restocks suspended.
- **Regional festival or demand event:** Specific items get +50% stock for the duration (festival = more food/drink merchants; war preparation = more weapons).
- **Faction control change:** When a settlement changes hands, all faction-affiliated merchants reset their inventory to match the new controlling faction's preferred goods.
- **Player intervention:** Quests can specifically modify merchant inventory ("clear the Hollow nest blocking the trade route" → restores normal restock).

The simulation tick reads active world events and applies modifiers before computing daily restock quantities.

---

### Merchant Gold Pool

Merchants have finite gold for buying player items. This creates economic geography — small settlements can't afford big-ticket purchases, driving players toward cities for high-value sales.

#### Daily Gold Allocations

| Settlement | General Merchant | Specialist Merchant (alchemist, weapons, jeweler) | Exotic Goods | Black Market |
|---|---|---|---|---|
| Hamlet | 10 sp | — (no specialists) | — | — |
| Village | 25 sp | 50 sp | — | — |
| Town | 75 sp | 150 sp | 200 sp | 100 sp |
| City | 200 sp | 400 sp | 600 sp | 300 sp |
| Capital | 500 sp | 1,000 sp | 1,500 sp | 800 sp |

These allocations represent the merchant's *liquid funds* on a given day. They restock daily at dawn (same cycle as inventory).

#### Gold Pool Mechanics

When a player sells an item to a merchant:

1. **If item value ≤ merchant's remaining gold:** Transaction proceeds normally. Player receives full appraised value (modified by disposition and faction). Merchant's gold pool decreases by the amount paid.

2. **If item value > merchant's remaining gold:** Three options:
   - **Partial purchase:** Merchant offers their remaining gold for the item. Player can accept (sell for less) or refuse.
   - **Refusal:** "I can't afford that. You'd want to take it to a city."
   - **Consignment:** At Friendly+ disposition, merchant offers to take the item on consignment — player leaves the item, merchant pays when they sell it (1d4 days, takes 10% commission). This is a deferred-payment system that requires player return visits.

3. **If merchant's gold pool is empty:** Merchant refuses all purchases until restock. They can still sell items to the player.

#### Settlement Personality Modifiers (Gold Pool)

Gold pool modifiers parallel inventory modifiers:

| Trait | Gold Pool Modifier |
|---|---|
| Prosperous | +50% |
| Struggling | -50% |
| Military | Standard for non-military goods. +100% for weapons/armor specifically (military pays well for arms) |
| Trade Hub | +25% |
| Isolated | -25% |
| Cursed/Corrupted | -75% |

**Example:** A Prosperous City Jeweler has a base 400 sp gold pool, modified to 600 sp. They can buy a 500 sp gem the player offers. A Struggling Village General Merchant has 25 sp × 0.5 = 12 sp — they can't afford the 50 sp short sword the player wants to sell, and recommend the next town.

#### Buyback Limits

Even within gold pool limits, merchants won't buy unlimited copies of the same item:

| Item Type | Max Same-Item Purchases per Day |
|---|---|
| Common weapons/armor | 3 |
| Common consumables | 5 |
| Quality items | 2 |
| Unique/specialty items | 1 |

**Beyond the limit, the merchant offers reduced prices** (50% of normal) or refuses entirely. The DM narrates: "I've already bought three short swords from you this week. Market's saturated. I'll give you 2 silver, but I can't go higher — and that's the last one I'll take."

This prevents farming exploits (kill a bandit camp, sell 12 short swords for full price) while still allowing reasonable trade.

---

### Special Inventory Categories

#### Traveling Merchants

Traveling merchants carry rotating inventory that changes between visits. Their stock is generated fresh each time they enter a settlement.

**Visit frequency:** Defined by route — typically 1 visit per real-week per settlement on their circuit. Hamlets see traveling merchants more frequently (they're often the only source of non-basic goods).

**Inventory generation:** When a traveling merchant arrives:
- Common goods drawn from `general_supplies` (0.5× quantity, since they have limited cart space)
- 1-2 items drawn from a higher-tier pool (`weapons_armor_quality`, `alchemical_supplies_common`, or `exotic_goods`) based on the merchant's specialization
- 1 unique "rumor item" — something acquired on their last circuit, often quest-relevant (a map fragment, a foreign artifact, news of a Hollow sighting)

**Stay duration:** 1-2 days per visit, then they leave. Their inventory does not restock during the visit.

**Pricing:** Traveling merchants charge +10% over standard prices (transportation cost) but are often the only source of rare goods in remote areas. They also pay slightly less when buying (-10%) due to transport limits.

#### Faction-Restricted Inventory

Some items are only available through faction-affiliated merchants and require minimum reputation tiers (see Faction Reputation Pricing). These don't restock through the standard system — they're authored per faction.

**Examples:**
- Thornwatch-issue equipment (requires Friendly+ Thornwatch)
- Keldaran-forged weapons (requires Trusted+ Keldaran Holds)
- Ashmark intelligence reports (requires Trusted+ Ashmark Order)

The faction merchants hold these items in reserve — they don't appear in standard inventory rolls. When a player at appropriate reputation visits, the items become available.

#### Quest-Locked Inventory

Specific items may be inventory-locked behind quest progression:
- "The blacksmith won't sell you the masterwork blade until you've recovered her stolen tools" (quest condition)
- "The alchemist's restricted reagents are unavailable until the player completes the Cleansing Rite quest" (faction trust gate via quest)

These items appear in the merchant's database as conditional entries — they only become visible/purchasable when the quest condition is met. The simulation handles this by checking quest state before exposing the item to the player.

---

### Voice-First Inventory Communication

Inventory in a voice game cannot be a menu. The DM must convey what's available through dialogue.

#### Shop Entry Narration

When the player enters a shop, the DM gives a high-level overview (3-4 highlights) rather than a complete inventory listing:

**Standard shop entry:**
> "Grimjaw's place is busy this morning. He's got a fresh batch of healing potions on the counter, and there's a longsword on the rack that wasn't there last week. Most of the usual supplies — rations, rope, that sort of thing. What can I help you with?"

**Sparse inventory:**
> "The shelves are thinner than last time. He's got rations and torches, the usual basics. A short sword in the corner, but that's about it for weapons. Hard times."

**Rich inventory (Prosperous, City):**
> "The shop is full — three different healing potions, an antitoxin, a couple of greater potions on the high shelf. She's got reagents you haven't seen since the last city. Anything in particular you're hunting for?"

The DM mentions Tier 2 limited stock items by name (that's where decisions matter), summarizes Tier 1 always-stocked items as a category ("the usual supplies"), and highlights Tier 3 unique items prominently.

#### Specific Item Inquiries

When the player asks for a specific item:

**Available:**
> "Healing potions? Yeah, I've got three left. 25 silver each."

**Out of stock (Tier 2 sold out):**
> "Healing potions? Sold the last one this morning to a Thornwatch patrol. I'll have more by tomorrow — supply runs in overnight."

**Unavailable (settlement size — wrong location):**
> "Plate armor? Friend, this is a village. You'd need to go to Tideholm or one of the bigger settlements for that kind of work."

**Unavailable (faction restriction):**
> "I don't sell that to just anyone. Maybe if you'd done some work for the Watch — but as it stands, no."

#### Selling to a Merchant

When the player offers an item:

**Within gold pool:**
> "That's a fine blade. I can give you 18 silver for it. Fair?"

**Beyond gold pool:**
> "I'll be honest — I don't have the coin for something that nice. I can offer 30 silver, all I've got liquid right now, or you could take it to the city where someone has the gold to pay what it's worth."

**Buyback limit reached:**
> "I've already taken three short swords off you this week. The market's flooded. I'll give you 2 silver — but that's the last one. Find a different town for the rest."

**Refusal:**
> "Stolen goods? Get out of my shop."

#### Restock Communication

The DM should narrate restock when contextually relevant:

> "The morning sun reaches the market, and merchants begin opening their stalls. Fresh stock is coming in — caravans arrived overnight."

This tells the player "the world has refreshed" without breaking immersion. After a long rest in town, the DM can reference the restock naturally:

> "After your rest, you head down to the market. Grimjaw waves you over — he's restocked since yesterday. Got new potions in."

#### What the DM Should Avoid

- **Listing exhaustive inventory.** Never recite the full stock — always summarize highlights and let the player ask for specifics.
- **Reading prices unprompted.** Prices come up in the natural flow of negotiation, not as a recited menu.
- **Mechanical language.** Never "your reputation modifier reduces this price by 15%" — instead, "the merchant gives you the friend's discount."
- **Inventory state dumps after every transaction.** Don't repeat full inventory after each purchase. Player can ask "what else do you have?" if they want.

---

### Implementation Reference

#### Data Structures

```python
# Stored in inventory_pools table (PostgreSQL JSONB)
{
  "id": "weapons_armor_basic",
  "tier_1_items": [
    # Always-stocked items (none in this pool — basic weapons are Tier 2)
  ],
  "tier_2_items": [
    {
      "item_id": "spear",
      "quantity_by_settlement": {
        "hamlet": [0, 0],  # min, max
        "village": [1, 3],
        "town": [2, 5],
        "city": [3, 8]
      }
    },
    # ... other items
  ],
  "tier_3_items": [
    {
      "item_id": "half_plate",
      "settlements": ["city", "capital"],
      "presence_chance": 0.25,
      "restock_check": "daily"
    }
  ]
}

# Stored in merchant_state table (Redis with PostgreSQL backing)
{
  "merchant_id": "grimjaw_hightown",
  "current_inventory": {
    "spear": 3,
    "dagger": 2,
    "leather_armor": 1,
    "shield": 2
    # ... only Tier 2/3 tracked; Tier 1 is implicit
  },
  "current_gold": 87,  # current liquid funds
  "max_gold": 150,  # daily allocation
  "last_restock_tick": 1730452800,
  "buyback_history": {
    "spear": 2,  # 2 spears bought from players today
    "leather_armor": 1
  },
  "consigned_items": [
    {
      "item_id": "masterwork_dagger",
      "owner_id": "player_xyz",
      "agreed_price": 75,
      "consignment_date": 1730452800,
      "expires": 1730712000  # 3 days
    }
  ]
}
```

#### Daily Restock Tick

```python
def daily_restock_at_dawn():
    """
    Runs once per in-game day at 06:00. Refreshes all merchant inventory and gold.
    Called by simulation tick layer 1 (time-driven).
    """
    for merchant in get_all_merchants():
        settlement = get_settlement(merchant.location)
        modifiers = get_settlement_modifiers(settlement)
        
        # Restock Tier 2 inventory
        pool = get_inventory_pool(merchant.inventory_pool_id)
        merchant.current_inventory = {}
        
        for item in pool.tier_2_items:
            base_range = item.quantity_by_settlement[settlement.size]
            quantity = random.randint(*base_range)
            quantity = round(quantity * modifiers.stock_multiplier)
            
            if quantity > 0:
                merchant.current_inventory[item.item_id] = quantity
        
        # Restock Tier 3 (probability check)
        if settlement.size in ['city', 'capital']:
            for item in pool.tier_3_items:
                if random.random() < item.presence_chance * modifiers.tier_3_chance:
                    merchant.current_inventory[item.item_id] = 1
        
        # Restock gold pool
        merchant.current_gold = round(merchant.max_gold * modifiers.gold_multiplier)
        
        # Reset buyback history
        merchant.buyback_history = {}
        
        # Check consignment expirations
        for consignment in merchant.consigned_items:
            if current_time > consignment.expires:
                # Item returned to consignor (or sold at discount, depending on rules)
                handle_expired_consignment(consignment)
        
        save_merchant_state(merchant)
```

#### Purchase Validation

```python
def attempt_purchase(player_id, merchant_id, item_id, quantity=1):
    merchant = get_merchant(merchant_id)
    item = get_item(item_id)
    
    # Check stock
    if item.tier == 1:
        # Always available
        pass
    elif merchant.current_inventory.get(item_id, 0) < quantity:
        return PurchaseResult(success=False, reason="out_of_stock")
    
    # Calculate price
    base_price = item.value_base * quantity
    price = apply_pricing_modifiers(base_price, player_id, merchant)
    
    # Check player gold
    if player.gold < price:
        return PurchaseResult(success=False, reason="insufficient_funds", price=price)
    
    # Check player inventory capacity
    if not can_carry(player_id, item, quantity):
        return PurchaseResult(success=False, reason="inventory_full")
    
    # Execute transaction
    player.gold -= price
    merchant.current_gold += price  # merchant gold pool grows from sales
    if item.tier > 1:
        merchant.current_inventory[item_id] -= quantity
    add_to_inventory(player_id, item_id, quantity)
    
    return PurchaseResult(success=True, price=price)


def attempt_sale(player_id, merchant_id, item_id, quantity=1):
    merchant = get_merchant(merchant_id)
    item = get_item(item_id)
    
    # Calculate offered price
    base_price = item.value_base * 0.5  # merchants buy at 50% of value (baseline)
    price = apply_pricing_modifiers(base_price, player_id, merchant)
    
    # Check buyback limit
    bought_today = merchant.buyback_history.get(item_id, 0)
    limit = get_buyback_limit(item)
    if bought_today >= limit:
        return SaleResult(success=False, reason="buyback_limit", 
                         counter_offer=price * 0.5)  # half-price counter
    
    # Check merchant gold pool
    if merchant.current_gold < price:
        return SaleResult(success=False, reason="merchant_low_funds",
                         counter_offer=merchant.current_gold,
                         consignment_available=(player.disposition >= "friendly"))
    
    # Execute transaction
    merchant.current_gold -= price
    player.gold += price
    remove_from_inventory(player_id, item_id, quantity)
    if item.tier > 1:
        merchant.current_inventory[item_id] = merchant.current_inventory.get(item_id, 0) + quantity
    merchant.buyback_history[item_id] = bought_today + 1
    
    return SaleResult(success=True, price=price)
```

---

### Design Decisions

> Extracted to `game_mechanics_decisions.md` for canonical reference.

**Decision 87: Three-tier stock model balances frictionless basics with meaningful scarcity.** Reason: an inventory system where every item can deplete creates frustration without gameplay value (running out of torches isn't a meaningful choice — it's just annoying). An inventory system where nothing depletes destroys the geography of trade. The three-tier model resolves this: trivial supplies are always available, quality goods can run out (creating real choices), and unique items create destination-driven gameplay. This mirrors real-world retail patterns players intuitively understand.

**Decision 88: Restock cadence is once per in-game day at dawn.** Reason: predictability matters. Players need to be able to plan around restock — "we'll rest in town tonight, the smith will have new stock in the morning." Probabilistic per-tick restock would create unpredictable patterns that players can't reason about. Daily cycles also give the world a natural rhythm and integrate cleanly with the existing time-driven simulation layer (no new infrastructure needed).

**Decision 89: Merchant gold pools are finite and scale with settlement size.** Reason: this creates economic geography. Small settlements can't afford big-ticket items, which drives players toward cities for high-value sales. Without this, settlement size becomes economically irrelevant — every shop is an infinite gold sink. The finite pool also creates interesting decisions: "do I sell the masterwork blade to the village smith for what he can afford, or carry it to the city for full price?" This is real gameplay. The implementation cost is modest — each merchant tracks one number that resets daily.

**Decision 90: Merchant gold pools restock daily at dawn, parallel to inventory.** Reason: consistency. Players already learn "restock happens at dawn" for inventory; extending the same rule to gold means one mental model, not two. This also prevents the edge case where a merchant has plenty of inventory but no gold to buy from the player (or vice versa) for asymmetric durations.

**Decision 91: Buyback limits prevent farming exploits.** Reason: without limits, a player could clear a bandit camp and unload twelve short swords on the village blacksmith for full price — far more than the in-world economy of a village should support. The buyback limit (3 same items per day for common weapons) reflects the reality that a village smith doesn't need twelve short swords. Beyond the limit, the merchant offers reduced prices, providing economic friction without hard refusal. This is an exploit-prevention mechanism that emerges naturally from the worldbuilding.

**Decision 92: Always-stocked items are limited to truly trivial supplies.** Reason: every item moved into Tier 1 (infinite stock) is one less point of friction in the economy. The line is drawn at items where running out creates frustration without gameplay (torches, rations). Quality items, even common ones (healing potions, basic weapons), are Tier 2 because their availability creates meaningful choices. The catalog of Tier 1 items is intentionally short and unlikely to grow.

**Decision 93: Consignment is a Friendly+ relationship feature, not a default option.** Reason: consignment requires the merchant to trust the player will return for payment, and trust the player won't dispute the eventual sale price. That trust requires existing relationship investment. Making consignment available only at Friendly+ disposition reinforces the relationship-investment loop (merchant likes you → unlocks consignment → enables high-value sales in small settlements → strengthens relationship). It also creates narrative content — "I'll hold onto this for you, Marn. Bring me your business when you can. We'll work out a fair price when it sells."

**Decision 94: Shop entry narration uses 3-4 highlights, not full inventory listing.** Reason: voice-first design. A complete inventory recitation would take 30+ seconds and overwhelm the player with information they'll forget. Highlights focus the player's attention on what's interesting (Tier 2 changes, Tier 3 presence) and lets them ask specific questions about the rest. This mirrors real shopping — you walk in, scan the highlights, ask about specifics.

**Decision 95: Settlement personality stacks multiplicatively on size.** Reason: the personality system already exists (`game_mechanics_npcs.md`) — leveraging it for inventory creates richer worldbuilding without new infrastructure. A Struggling Village feels meaningfully different from a Prosperous Village even though both are Villages. The multiplicative stacking ensures personality matters at every settlement size — a Struggling City is still richer than a Struggling Village, but both feel poorer than their Prosperous counterparts.
