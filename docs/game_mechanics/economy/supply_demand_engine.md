# Supply & Demand Engine — Economy Section

> **Integration note:** This section replaces the "Supply & Demand Engine" stub in `game_mechanics_economy.md` under "Systems Not Yet Specified." Cross-references: `world_data_simulation.md` (simulation tick, events, value_modifiers), `game_mechanics_economy.md` (Merchant Pricing Formula, Faction Reputation Pricing), `merchant_inventory_restock.md` (stock multipliers under settlement personality).

---

## Supply & Demand Engine

### Design Philosophy

Prices change because the world changes. A Hollow incursion drives up healing potion costs because demand spikes and supply chains break. A successful trade route restoration brings prices back down. The player should *feel* these shifts through play — not just see numbers move, but understand why ("the alchemists have been running low since the incursion").

The system is a layer on top of the existing pricing infrastructure. Items already have a `value_modifiers` field that supports condition-based pricing. The simulation tick (layer 2) already runs the price adjustment logic. This section defines *what events exist*, *how much they affect prices*, and *how they resolve over time*.

---

### Magnitude and Stacking Rules

#### Hard Bounds

All final computed prices are clamped to the range **0.5× to 3.0×** of the item's `value_base`. These bounds apply to the *combined* result of all modifiers (events, disposition, faction, regional, etc.).

| Bound | Multiplier | Rationale |
|---|---|---|
| Floor | 0.5× | Below this, items become effectively free and break crafting/trading economics. Worst possible discount is 50% off |
| Ceiling | 3.0× | Above this, items become effectively unavailable and frustrate without creating gameplay. Worst possible markup is 200% over base |

Individual events typically apply smaller multipliers (1.1× to 2.0× for crisis events; 0.7× to 0.9× for surplus events). The bounds exist as a safety net for unexpected stacking, not as a target range for individual events.

#### Stacking Rule: Multiplicative with Final Clamp

When multiple events affect the same item, modifiers stack multiplicatively:

```
event_modifier = product of all active event multipliers
final_price = base_price × disposition_mod × faction_mod × event_modifier
final_price = clamp(final_price, base_price × 0.5, base_price × 3.0)
```

**Example:** Healing Potion (`value_base = 25 sp`) at a merchant during a Hollow Incursion (1.5× on `healing` tag), Disease Outbreak (1.4× on `healing` tag), and Trade Route Disruption (1.2× on all goods).

```
event_modifier = 1.5 × 1.4 × 1.2 = 2.52
With Friendly disposition (0.9×) and Neutral faction (1.0×):
final_price = 25 × 0.9 × 1.0 × 2.52 = 56.7 sp ≈ 57 sp
clamp check: 12.5 sp ≤ 57 sp ≤ 75 sp ✓ (within bounds)
```

The player feels the crisis — what cost 25 sp now costs 57 sp. But the crisis isn't infinite — even if more events stacked, the price would never exceed 75 sp.

**Why multiplicative stacking:** Events represent *independent* market pressures. A Hollow incursion creates demand pressure; a trade route disruption creates supply pressure. Both are real and both should compound. Additive stacking would understate the impact of confluence (real crises feel like crises). The 3.0× cap prevents pathological cases.

---

### Item Tag Taxonomy (Economic)

Events affect items via tags. Items already carry tags in their schema (e.g., `"protective"`, `"anti-hollow"`, `"healing"`, `"thornwatch"`). The supply-and-demand system uses a standardized economic tag taxonomy that complements existing narrative tags:

#### Economic Tags

| Tag | Includes | Used By Events |
|---|---|---|
| `healing` | Healing potions, healer's kits, antitoxins, bandages, medicinal herbs | Hollow Incursion, Disease Outbreak, War, Plague |
| `anti-hollow` | Hollow-Ward Amulets, blessed weapons, holy water, anti-Hollow oil, purification kits | Hollow Incursion, Hollow Sighting, Veil Disturbance |
| `divine` | Holy symbols, blessed items, prayer goods, religious texts, sanctified relics | Religious Pilgrimage, Divine Crisis, Faith Surge |
| `weapons` | All weapons (martial, simple, ranged) | War, Bandit Activity, Military Mobilization, Mine Closure (metal weapons specifically) |
| `armor` | All armor (light, medium, heavy, shields) | War, Military Mobilization, Mine Closure |
| `food` | Rations, fresh food, dried goods, drinks, agricultural products | Drought, Bumper Harvest, Festival, Refugee Influx, War |
| `travel` | Rope, bedrolls, tents, lanterns, oil flasks, torches, backpacks | Bandit Activity, Trade Route events, Refugee Influx |
| `luxury` | Jewelry, gems, fine clothing, exotic imports, decorative goods | Festival, Recession, War (luxury → necessity shift) |
| `crafting_material` | Raw ores, hides, herbs, reagents, components | Mine Closure, Forest Corruption, Bumper Harvest |
| `imported` | Foreign goods, exotic items, items from distant regions | Trade Route Disrupted, Trade Route Reopened |
| `military` | Faction military equipment (Thornwatch, Ashmark, Keldaran issue) | War, Military Mobilization, Faction Conflict |

A single item may carry multiple economic tags. A Hollow-Ward Amulet is both `anti-hollow` and `divine` (since it's blessed). A Thornwatch-issue chain shirt is both `armor` and `military`. When multiple tags match an event, the event applies to the item — the multiplier doesn't stack across tags within a single event.

#### Tag Inheritance

Items also inherit economic tags from their material composition. A weapon crafted from rare ore is automatically tagged `crafting_material` for purposes of supply events (a Mine Closure event affects items made from the affected metal, not just raw ore). This is computed at item generation time, not at runtime.

---

### Event Lifecycle (Three Phases)

Economic events progress through three phases. Each phase has its own multiplier scaling.

#### Phase 1: Active

The event is occurring. Full multiplier effects apply. Phase begins when trigger conditions are met.

**Duration:** Variable per event type. Minor events (bandit activity, small festivals) last 1-3 in-game days. Major events (regional plague, sustained Hollow incursion) last 1-3 in-game weeks. Some events end only when player intervention resolves them (clear the Hollow nest, defeat the bandit captain).

**Multiplier:** As defined per event (typically 1.3× to 2.0× for crises, 0.7× to 0.9× for surpluses).

#### Phase 2: Recovery

The event has resolved (player intervention, time expiration, or world state change), but its effects linger. The market is healing but hasn't normalized.

**Duration:** Half the active phase duration, minimum 2 in-game days. A 7-day plague has a 3-4 day recovery; a 1-day festival has a 2-day recovery.

**Multiplier:** Decays linearly from full event multiplier toward 1.0× over the recovery duration.

```
recovery_progress = (current_time - recovery_start_time) / recovery_duration
recovery_progress = clamp(recovery_progress, 0, 1)
recovery_multiplier = active_multiplier + (1.0 - active_multiplier) × recovery_progress
```

**Example:** A Hollow Incursion event with active multiplier 1.5× on `healing` items resolves on day 7. Recovery duration is 4 days.
- Day 7 (recovery start): multiplier = 1.5×
- Day 8 (25% recovered): multiplier = 1.5 + (1.0 - 1.5) × 0.25 = 1.375×
- Day 9 (50% recovered): multiplier = 1.25×
- Day 10 (75% recovered): multiplier = 1.125×
- Day 11 (100% recovered, recovery ends): multiplier = 1.0× → event transitions to Resolved

#### Phase 3: Resolved

The event no longer affects prices. The event remains in the world events log for narrative reference but has no mechanical effect.

**Duration:** Permanent. The event is historical.

**Multiplier:** None. No effect on prices.

#### Why Three Phases

Without recovery, prices snap back to normal the moment a player kills the Hollow boss — narratively unsatisfying and ahistorical (real supply chains take time to rebuild). With recovery, the player feels their intervention through gradual price normalization, narrated by the DM ("the alchemists are restocking; prices are easing back down"). This makes the world feel responsive without being instantaneous.

---

### Catalog of Standard Economic Events

The following events form the baseline economic event set. Each event is a content data record in the `events` table (per `world_data_simulation.md`), with `type: "economic"`. Specific events may be authored in addition (faction-driven events, quest-triggered events, seasonal events).

#### Demand-Driven Events (raise prices through demand spikes)

##### Hollow Incursion
**Trigger:** Regional `hollow_corruption >= 6` for 3+ in-game days, OR named Hollow creature defeated nearby (within 1 in-game week).
**Active duration:** Until corruption drops below 4, OR 2 in-game weeks elapsed, whichever comes first.
**Recovery duration:** 1 in-game week.
**Effects:**

| Tag | Active Multiplier | Notes |
|---|---|---|
| `anti-hollow` | 2.0× | Highest demand. The crisis is here, people need protection |
| `healing` | 1.5× | Casualties create medical demand |
| `divine` | 1.4× | People turn to faith in dark times |
| `weapons` | 1.2× | Mild military demand spike |

**Affected region:** The settlement where corruption is highest, plus all settlements within trade range (one travel-day).

##### Bandit Activity
**Trigger:** Bandit camp established near trade route (faction simulation creates), OR 3+ bandit attacks reported within in-game week.
**Active duration:** Until camp cleared, OR 2 in-game weeks elapsed.
**Recovery duration:** 3 in-game days.
**Effects:**

| Tag | Active Multiplier | Notes |
|---|---|---|
| `travel` | 1.4× | Travelers need supplies but afraid to journey |
| `weapons` | 1.3× | Self-defense demand |
| `armor` | 1.3× | Self-defense demand |
| `imported` | 1.5× | Supply chain disruption from interrupted caravans |

**Affected region:** Settlements along the disrupted trade route.

##### Disease Outbreak
**Trigger:** Plague event fires (random or quest-driven), OR `disease_active` flag set on region.
**Active duration:** 1-3 in-game weeks (varies by disease severity).
**Recovery duration:** Half the active duration, minimum 1 week.
**Effects:**

| Tag | Active Multiplier | Notes |
|---|---|---|
| `healing` | 1.7× | Medical supplies in dire demand |
| `divine` | 1.3× | Healing prayers, religious comforts |
| `food` | 1.2× | Hoarding behavior |

**Affected region:** Originating settlement and all settlements within travel range. Disease may spread through the simulation, expanding the affected area.

##### War / Military Mobilization
**Trigger:** Faction conflict declared (faction simulation), OR `military_buildup` flag set on region.
**Active duration:** Until conflict resolved (variable, often weeks to months).
**Recovery duration:** 1 in-game week minimum, longer for protracted wars.
**Effects:**

| Tag | Active Multiplier | Notes |
|---|---|---|
| `weapons` | 1.6× | Massive military demand |
| `armor` | 1.6× | Equipment for soldiers |
| `food` | 1.4× | Army supply requirements |
| `military` | 1.8× | Faction-specific gear in highest demand |
| `luxury` | 0.7× | Wartime austerity reduces luxury demand |

**Affected region:** Faction-controlled territory.

##### Religious Pilgrimage / Divine Crisis
**Trigger:** Religious holiday on world clock, OR god-agent action triggers pilgrimage event.
**Active duration:** 1-2 in-game weeks.
**Recovery duration:** 3 in-game days.
**Effects:**

| Tag | Active Multiplier | Notes |
|---|---|---|
| `divine` | 1.5× | Pilgrim demand for religious goods |
| `food` | 1.2× | Pilgrim influx strains food supply |
| `healing` | 1.1× | Travel-related minor demand |

**Affected region:** Pilgrimage destination settlement(s).

##### Refugee Influx
**Trigger:** Major event displaces population (Hollow incursion, war, disaster).
**Active duration:** 2-4 in-game weeks (depends on root cause resolution).
**Recovery duration:** 1 in-game week.
**Effects:**

| Tag | Active Multiplier | Notes |
|---|---|---|
| `food` | 1.5× | Sudden population spike strains food supply |
| `travel` | 1.3× | Refugees buying basic supplies |
| `healing` | 1.3× | Medical needs of displaced people |

**Affected region:** Settlement receiving refugees.

#### Supply-Driven Events (raise prices through supply restriction)

##### Trade Route Disrupted
**Trigger:** Bandit activity event, Hollow corruption blocks route, war between factions controlling route, natural disaster.
**Active duration:** Until disruption resolved.
**Recovery duration:** 5 in-game days (rebuilding caravan trust takes time).
**Effects:**

| Tag | Active Multiplier | Notes |
|---|---|---|
| `imported` | 1.8× | Direct hit on imported goods |
| `luxury` | 1.5× | Luxury often imported |
| `crafting_material` | 1.3× | Raw materials often traded over distance |

**Affected region:** Settlements that depend on the disrupted route.

##### Mine Closure
**Trigger:** Mine attacked by Hollow, mine collapse event, faction takeover restricting access.
**Active duration:** Until mine reopened (often quest-resolved).
**Recovery duration:** 1 in-game week.
**Effects:**

| Tag | Active Multiplier | Notes |
|---|---|---|
| `weapons` | 1.4× | Metal weapons affected |
| `armor` | 1.5× | Metal armor heavily affected |
| `crafting_material` | 1.7× | Raw ore directly impacted |

**Affected region:** Settlements that source from the affected mine (typically regional, sometimes nation-wide).

##### Forest Corruption
**Trigger:** Hollow corruption reaches forested region (`hollow_corruption >= 7` in forest biome).
**Active duration:** Until corruption cleared (often only by major quest intervention).
**Recovery duration:** 2 in-game weeks (forest healing is slow).
**Effects:**

| Tag | Active Multiplier | Notes |
|---|---|---|
| `crafting_material` | 1.6× | Wood, herbs, fibers all affected |
| `food` | 1.3× | Forest game and gathering reduced |
| `healing` | 1.4× | Many medicinal herbs come from healthy forest |

**Affected region:** Settlements that source from the affected forest.

##### Drought
**Trigger:** Weather simulation produces sustained drought conditions.
**Active duration:** Until weather pattern shifts (1-4 in-game weeks).
**Recovery duration:** 1 in-game week (next harvest cycle).
**Effects:**

| Tag | Active Multiplier | Notes |
|---|---|---|
| `food` | 1.6× | Crop failure |
| `crafting_material` | 1.2× | Some materials are agricultural |

**Affected region:** Agricultural settlements in drought zone.

##### Faction Embargo
**Trigger:** Faction relationship deteriorates to "hostile" with another faction's territory, OR specific faction quest trigger.
**Active duration:** Until diplomatic resolution.
**Recovery duration:** 1 in-game week.
**Effects:**

| Tag | Active Multiplier | Notes |
|---|---|---|
| `military` (embargoed faction) | 2.0× | Faction goods become rare and contraband |
| `imported` | 1.3× | If embargoed faction was a trade source |

**Affected region:** Embargoing faction's territory.

#### Surplus Events (lower prices)

##### Bumper Harvest
**Trigger:** Weather simulation produces ideal growing conditions, OR successful agricultural quest outcome.
**Active duration:** 2 in-game weeks (harvest season abundance).
**Recovery duration:** 1 in-game week.
**Effects:**

| Tag | Active Multiplier | Notes |
|---|---|---|
| `food` | 0.7× | Genuine surplus reduces price |
| `crafting_material` | 0.85× | Some agricultural materials surplus |

**Affected region:** Agricultural settlements in harvest zone.

##### Successful Mining Operation
**Trigger:** New vein discovered (random event), OR successful mining quest outcome.
**Active duration:** 2-4 in-game weeks.
**Recovery duration:** 1 in-game week.
**Effects:**

| Tag | Active Multiplier | Notes |
|---|---|---|
| `weapons` | 0.85× | Cheaper materials → cheaper goods |
| `armor` | 0.85× | Cheaper materials → cheaper goods |
| `crafting_material` | 0.7× | Direct surplus on ore |

**Affected region:** Settlements supplied by the mine.

##### Festival
**Trigger:** Cultural calendar (Aelindran Lantern Festival, Keldaran Forge Day, etc.), OR settlement-specific celebration triggered by quest/event.
**Active duration:** 1-3 in-game days.
**Recovery duration:** 2 in-game days.
**Effects:**

| Tag | Active Multiplier | Notes |
|---|---|---|
| `food` | 0.85× | Festival food often subsidized or competitive |
| `luxury` | 0.9× | Luxury merchants compete for festival attention |
| `divine` | 1.2× | Some festivals raise divine demand |

**Affected region:** Festival settlement and immediate surroundings.

##### Faction Surplus
**Trigger:** Faction concludes successful military campaign or completes major operation, leaving them with surplus equipment.
**Active duration:** 1-2 in-game weeks.
**Recovery duration:** 1 in-game week.
**Effects:**

| Tag | Active Multiplier | Notes |
|---|---|---|
| `military` (relevant faction) | 0.7× | Surplus arms and armor flood the market |
| `weapons` | 0.9× | General market effect |
| `armor` | 0.9× | General market effect |

**Affected region:** Faction-controlled territory.

---

### Worked Example: Multi-Event Crisis

A Hollow incursion strikes a settlement near the Hollowmere border. Within days, the local trade route is disrupted by Hollow creatures preventing caravans. A week later, refugees from a smaller adjacent settlement flee to the affected town.

**Active events at the regional capital:**

| Event | Phase | Multipliers |
|---|---|---|
| Hollow Incursion | Active (day 8 of 14) | `anti-hollow` 2.0×, `healing` 1.5×, `divine` 1.4×, `weapons` 1.2× |
| Trade Route Disrupted | Active (day 5 of unknown) | `imported` 1.8×, `luxury` 1.5×, `crafting_material` 1.3× |
| Refugee Influx | Active (day 2 of ~21) | `food` 1.5×, `travel` 1.3×, `healing` 1.3× |

**Effective multipliers per tag:**

| Tag | Computed Multiplier | Final (after clamp) |
|---|---|---|
| `anti-hollow` | 2.0× | 2.0× |
| `healing` | 1.5 × 1.3 = 1.95× | 1.95× |
| `divine` | 1.4× | 1.4× |
| `weapons` | 1.2× | 1.2× |
| `imported` | 1.8× | 1.8× |
| `luxury` | 1.5× | 1.5× |
| `crafting_material` | 1.3× | 1.3× |
| `food` | 1.5× | 1.5× |
| `travel` | 1.3× | 1.3× |

**Sample item prices for this player (Friendly disposition with merchant, Trusted faction reputation with Thornwatch):**

| Item | Tags | Base Price | Final Price | Player Experience |
|---|---|---|---|---|
| Healing Potion | `healing`, `consumable` | 25 sp | 25 × 0.9 × 0.9 × 1.95 = 39 sp | "Potions are getting expensive. The alchemist's working overtime" |
| Hollow-Ward Amulet | `anti-hollow`, `divine`, `protective` | 150 sp | 150 × 0.9 × 0.9 × 2.0 = 243 sp | "She's selling these as fast as she can make them. Three times what they normally cost" |
| Rations (1 day) | `food`, `consumable` | 5 cp | 5 × 0.9 × 0.9 × 1.5 = ~6 cp | Slight increase, barely noticeable on common goods |
| Longsword | `weapons`, `martial` | 10 sp | 10 × 0.9 × 0.9 × 1.2 = 10 sp | Roughly normal — weapons aren't the bottleneck here |
| Imported wine | `luxury`, `imported` | 8 sp | 8 × 0.9 × 0.9 × 1.5 × 1.8 = 17 sp (clamped: 24 sp max) | "Caravans aren't getting through. Wine's not worth what it used to be" |

The player feels the crisis viscerally — anti-Hollow gear is unaffordable for the casual buyer, and even daily supplies are noticeably more expensive. The Faction reputation discount (Trusted Thornwatch) softens the blow, making Thornwatch-affiliated merchants the player's best option during the crisis.

When the player resolves the Hollow incursion (Phase shifts to Recovery), prices begin returning to normal over the next week. The DM narrates the transition: "The market's busier today. Caravans are running again. Maren's prices on the healing potions are coming back down — she said to thank you."

---

### Implementation Reference

#### Data Structures

```python
# Event instance state (stored in world_events_log table)
{
  "event_id": "hollow_incursion_veldross_2026_03_15",
  "event_template": "hollow_incursion",
  "phase": "active",  # active | recovery | resolved
  "started_at": 1736896000,
  "phase_started_at": 1736896000,
  "active_duration_seconds": 1209600,  # 14 in-game days
  "recovery_duration_seconds": 604800,  # 7 in-game days
  "affected_regions": ["veldross", "veldross_borderlands"],
  "active_multipliers": {
    "anti-hollow": 2.0,
    "healing": 1.5,
    "divine": 1.4,
    "weapons": 1.2
  },
  "resolution_conditions": {
    "hollow_corruption_below": 4,
    "or_time_elapsed": True
  }
}
```

#### Price Calculation

```python
def compute_item_price(item, merchant, player) -> int:
    """
    Computes the final price an item is offered at by a merchant to a player.
    All modifiers stack multiplicatively, clamped to [0.5x, 3.0x] of base price.
    """
    base = item.value_base
    
    # Disposition modifier (per Merchant Pricing Formula)
    disposition_mod = DISPOSITION_MODIFIERS[merchant.disposition_to(player)]
    
    # Faction reputation modifier (per Faction Reputation Pricing)
    faction_mod = compute_faction_modifier(merchant.faction, player.reputation)
    
    # Event modifiers (this section)
    event_mod = 1.0
    active_events = get_active_events_for_region(merchant.region)
    
    for event in active_events:
        # Determine effective multiplier based on phase
        if event.phase == "active":
            event_multipliers = event.active_multipliers
        elif event.phase == "recovery":
            event_multipliers = compute_recovery_multipliers(event)
        else:
            continue  # resolved events have no effect
        
        # Apply each matching tag (only once per event, even if item has multiple matching tags)
        applied_this_event = False
        for tag, multiplier in event_multipliers.items():
            if tag in item.economic_tags and not applied_this_event:
                event_mod *= multiplier
                applied_this_event = True
    
    # Item-specific value_modifiers (existing system: regional, contextual)
    context_mod = compute_context_modifiers(item, merchant.region, player)
    
    # Combine all modifiers
    final_price = base * disposition_mod * faction_mod * event_mod * context_mod
    
    # Clamp to bounds
    final_price = max(base * 0.5, min(base * 3.0, final_price))
    
    return round(final_price)


def compute_recovery_multipliers(event) -> dict:
    """
    Computes the current multiplier values for an event in recovery phase.
    Linear decay from active_multiplier toward 1.0 over recovery duration.
    """
    elapsed = current_time() - event.phase_started_at
    progress = min(1.0, elapsed / event.recovery_duration_seconds)
    
    recovery_multipliers = {}
    for tag, active_mult in event.active_multipliers.items():
        recovery_multipliers[tag] = active_mult + (1.0 - active_mult) * progress
    
    return recovery_multipliers
```

#### Simulation Tick Integration

The simulation tick (every 10 minutes real-time) handles event lifecycle:

```python
def economy_simulation_tick():
    """
    Runs every 10 minutes. Updates event lifecycle and triggers new events.
    """
    now = current_time()
    
    # Update existing events
    for event in get_all_active_events():
        if event.phase == "active":
            # Check resolution conditions
            if event_resolution_conditions_met(event) or event_active_duration_expired(event):
                event.phase = "recovery"
                event.phase_started_at = now
                emit_event_phase_transition(event)
        
        elif event.phase == "recovery":
            # Check if recovery duration elapsed
            if (now - event.phase_started_at) >= event.recovery_duration_seconds:
                event.phase = "resolved"
                emit_event_phase_transition(event)
    
    # Trigger new events
    for event_template in get_event_templates(type="economic"):
        if event_template_conditions_met(event_template):
            instantiate_event(event_template)
    
    # Invalidate price caches for affected regions
    for region in affected_regions:
        redis.delete(f"region:{region}:prices")
```

Prices are computed on-demand when a player interacts with a merchant. They're cached briefly (60-second TTL in Redis) for performance, invalidated when event state changes.

---

### DM Narration Patterns

The player must understand *why* prices have changed. The DM narrates the cause; the character sheet shows the effect.

#### Event Onset

When the player enters a settlement experiencing an active economic event, the DM narrates the situation:

**Hollow Incursion:**
> "The market is tense. Half the stalls are shuttered. The ones that are open have crowds around them — people buying anti-Hollow charms, healing supplies, anything that might help. Maren's selling Hollow-Ward Amulets for three times the usual price, and she still can't keep them in stock."

**Bandit Activity on Trade Routes:**
> "The town feels different from your last visit. The market is thinner, prices on imported goods have crept up. The merchants you talk to all mention the same thing: caravans aren't getting through. Bandits in the pass."

**Disease Outbreak:**
> "There's a smell of burning herbs in the air — the kind temples use to ward off plague. Half the people in the market are wearing cloth masks. The healer's shop has a line out the door, and her prices have jumped. She apologizes — supplies are running thin."

**Bumper Harvest:**
> "The grain merchant is in good spirits. 'Best harvest in five years. Rations are practically free this season — get them while you can.' The whole market feels lighter."

#### Specific Item Inquiries During Events

When the player asks about a specific item that's been affected:

**Active phase:**
> "Healing potions? I've got two left. Forty silver each — I know, I know. The incursion's got everyone buying them faster than I can brew. Won't get more reagents for at least a week."

**Recovery phase:**
> "Healing potions are coming back down — twenty-eight silver. Reagents are flowing again. Give it another few days and we'll be back to normal pricing."

**Resolved phase:**
> "Twenty-five silver, same as ever. The incursion's a memory now. Quieter times."

#### Cross-Settlement Awareness

The DM can hint that the player should travel to find better prices when local conditions are bad:

> "Anti-Hollow gear is going to cost you a fortune here. If you've got the time, you'd do better in Tideholm — they're further from the corruption, prices haven't gone up nearly as much."

This creates organic geographic gameplay — the world's economic state becomes part of the player's strategic considerations.

#### Player Intervention Acknowledgment

When the player resolves an event (kills the Hollow boss, clears the bandit camp), the DM acknowledges it through the merchant's voice:

> "Maren's smiling for the first time in weeks. 'Heard about what you did at the breach. Caravans are running again — first one came in this morning. Prices are coming back down. Take this potion — on the house. Thank you.'"

The +1 disposition shift from this moment is mechanical; the recovery-phase price decay is automatic. But the *narrative* connection — "I solved this and the world responded" — is what the player remembers.

---

### Design Decisions

> Extracted to `game_mechanics_decisions.md` for canonical reference.

**Decision 96: Hard price bounds clamp final prices to [0.5×, 3.0×] of base.** Reason: without bounds, multiplicative stacking can produce pathological prices (5+ events stacked = 7-10× base, breaks player ability to transact). The 0.5× floor preserves crafting/trading economics; the 3.0× ceiling preserves player ability to buy critical items even in the worst crises. Bounds are a safety net, not a target — most events stay well within them.

**Decision 97: Event modifiers stack multiplicatively, not additively.** Reason: events represent independent market pressures. A Hollow incursion creates demand pressure; a trade route disruption creates supply pressure; a refugee influx adds population pressure. All three are real and all three should compound. Additive stacking would understate the impact of confluence — three separate crises wouldn't feel like a real disaster. Multiplicative stacking with a 3.0× clamp captures both the compounding and the protective ceiling.

**Decision 98: Item granularity is tag-based, not category-based.** Reason: the item schema already supports tags. A Hollow incursion specifically demands `anti-hollow` items, not all weapons — Hollow-Ward Amulets and blessed weapons see massive demand spikes, while a regular dagger is barely affected. Tag-based targeting also lets us layer events naturally (Hollow Incursion affects `anti-hollow` and `healing` and `divine`, each at different multipliers) without artificial categorization. Tags also handle multi-attribute items naturally — a blessed sword is both `weapons` and `divine`, and gets the highest applicable event modifier.

**Decision 99: Tag matching is once-per-event, not stacking across tags within an event.** Reason: if a Hollow Incursion event boosts both `anti-hollow` (2.0×) and `divine` (1.4×), and an item has both tags, applying both would yield 2.8× — which over-counts the same demand pressure. Instead, the event's strongest applicable tag wins for that item. This ensures multiple events compound (independent pressures), but redundant tag effects within a single event don't double-count.

**Decision 100: Events have three phases (Active / Recovery / Resolved) with linear recovery decay.** Reason: binary on-off events create jarring "prices snap to normal the moment you kill the boss" moments. Real economies recover gradually — supply chains rebuild, fear subsides, surpluses get absorbed. The recovery phase makes the world feel responsive but realistic. Linear decay is mathematically simple and produces intuitive narration ("prices are coming back down"). The three-phase model adds minimal state (one extra field per event instance) for significant narrative gain.

**Decision 101: Recovery duration is half active duration, minimum 2 in-game days.** Reason: recovery shouldn't be instantaneous (defeats the purpose) or longer than the original crisis (would feel disproportionate). Half-duration with a 2-day floor produces good results across the range — a 14-day Hollow incursion has a 7-day recovery; a 1-day festival has a 2-day recovery. Players experience meaningful but bounded recovery periods.

**Decision 102: Player intervention can resolve events early; time-based resolution is the fallback.** Reason: agency matters. The player should be able to *cause* recovery by acting (defeating the Hollow boss, clearing the bandit camp, completing the plague-cure quest). But events shouldn't be permanent if the player ignores them — the world keeps moving, threats burn out or get resolved by NPC factions over time. Active duration is a maximum; resolution conditions can end events sooner. This balances agency with world-as-living-system.

**Decision 103: DM narrates causes; character sheet shows numbers.** Reason: voice-first design. The DM never says "healing potions are 1.95× their normal price due to active Hollow Incursion (1.5×) and Disease Outbreak (1.3×) events." The DM says "the alchemists are running low — the incursion's been brutal on supplies." The character sheet shows the actual price (39 sp instead of 25 sp). Players learn to read the world's narrative state and connect it to mechanical impact, which is a core gameplay loop in a voice-first RPG.

**Decision 104: Event narration should reference player intervention for resolved events.** Reason: making the player's actions narratively visible is critical for agency. When prices come back down because the player solved the underlying crisis, the merchant should mention it. "Heard about what you did at the breach — caravans are running again." This creates the closed loop: player acts → world changes → merchant notices → player feels their impact. Without this narration, recovery feels like passive time-passing rather than earned consequence.
