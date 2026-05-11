# Gold Sink Ledger — Economy Section

> **Integration note:** This section replaces the "Gold Sinks" stub in `game_mechanics_economy.md` under "Systems Not Yet Specified." This is primarily a *consolidation* document — most sinks already exist mechanically across other files. The ledger view exists to verify economic balance, identify gaps, and provide a canonical reference for inflation control. Cross-references: `game_mechanics_combat.md` (death economy), `game_mechanics_crafting.md` (item degradation, repair), `game_mechanics_npcs.md` (services, mentor fees, lodging), `game_mechanics_core.md` (Training cycles), `faction_reputation_pricing.md` (donations, faction services), `merchant_inventory_restock.md` (consignment fees).

---

## Gold Sink Ledger

### Design Philosophy

A *gold sink* is any mechanism that permanently removes currency from the player's economy. Sinks balance against *gold sources* (faucets) — quest rewards, loot sales, faction bounties — to prevent runaway inflation in the long-term world economy.

#### What Makes a Good Gold Sink

Good sinks share four properties:

1. **Connected to gameplay, not arbitrary tax.** The player pays *for something* — a service, a benefit, a removed problem. Pure tolls (walked into the city, lost 10 sp) feel punitive. A dispel corruption service that removes a debilitating condition feels valuable.

2. **Choice-driven, not forced.** Most sinks should be voluntary or contextual. The player chooses to pay for the fine room over the common room, the masterwork blade over the standard sword, the immediate Revivify over the longer-term resurrection trip. Forced sinks (death costs after Resurrection) should always be recoverable through play.

3. **Scales with player wealth.** A 5 sp sink that's meaningful at level 1 is trivial at level 15. The best sinks are tiered (repair: 2/10/50/200+ sp by item rarity) or recurring (workspace rental: 2-12 sp/day for active crafters). Flat-fee sinks become economically irrelevant at higher levels.

4. **Has narrative justification.** The sink connects to worldbuilding. Mortaen's diamond requirement for Revivify is mechanical (50 gc removed from economy) and narrative (the god of death demands tribute for crossing the threshold). The cost makes sense in the world.

#### What Makes a Bad Gold Sink

- **Pure taxation:** Fees for entering settlements, breathing air, having a backpack.
- **Disconnected from world:** "Random merchant fee" with no in-fiction reason.
- **Doesn't scale:** Flat 5 sp fees that became trivial 30 levels ago.
- **Frustrating without recourse:** Forced costs the player can't avoid or mitigate.
- **Punishes desired play:** Sinks that discourage exploration, social engagement, or experimentation.

The Divine Ruin sink design favors voluntary, contextual, scaling, narratively-justified sinks. We avoid pure taxation. Forced sinks are limited to natural consequences (death, durability) with player agency to mitigate them.

---

### Categorization Framework

Sinks fall into eight categories based on player choice and triggering condition:

| Category | Choice Level | Triggering Condition | Example |
|---|---|---|---|
| **Maintenance** | Forced | Item degradation, durability loss | Repairing a damaged longsword |
| **Subsistence** | Contextual | Travel, exploration, day-to-day living | Buying rations, paying for lodging |
| **Combat** | Situational | Combat outcomes, death, injury | Healing potions consumed, resurrection diamond |
| **Progression** | Voluntary | Character growth opportunities | Mentor training fees, faction donations |
| **Crafting** | Voluntary | Engaging with the crafting system | Commissioning a blacksmith, renting a forge |
| **Service** | Voluntary | Specialized NPC services | Identify item, research, translate text |
| **Lifestyle** | Voluntary | Expressive choices, luxury preferences | Fine room over common room, exotic goods |
| **Endgame** | Voluntary | High-tier player wealth absorption | Legendary repair, faction investments, resurrection |

The eight categories serve different design purposes:

- **Maintenance** keeps long-held items costing something to use (combat-as-friction).
- **Subsistence** ensures money doesn't sit idle during exploration (always-spending).
- **Combat** creates real stakes for fights and bad outcomes (consequence-as-cost).
- **Progression** lets the player invest in long-term capability (skill-as-economy).
- **Crafting** absorbs wealth from active crafters (production-cost).
- **Service** provides shortcuts and conveniences for those who can afford them (time-for-money).
- **Lifestyle** rewards wealth without granting mechanical advantage (status-as-expression).
- **Endgame** absorbs the wealth of high-level players to control inflation (cap-on-hoarding).

---

### The Complete Ledger

#### Maintenance Sinks

##### Item Repair

Items degrade through use (combat damage, environmental wear, Hollow corruption exposure). Repair restores condition. Source: `game_mechanics_crafting.md` (item degradation), `game_mechanics_economy.md` (repair pricing).

| Item Tier | Repair Cost | Frequency | Notes |
|---|---|---|---|
| Common | 2 sp | After 5-10 combats | Standard weapons, basic armor |
| Uncommon | 10 sp | After 5-10 combats | Quality weapons, studded leather, chain shirt |
| Rare | 50 sp | After 5-10 combats | Half plate, plate, masterwork weapons |
| Legendary | 200+ sp | After 5-10 combats | Magical items, named gear, Tier 3+ items |

**Estimated drain per session:** 5-50 sp depending on item tier and combat frequency. Scales naturally with player gear progression.

**Player agency:** Players with Crafting skill can repair their own items at no cost (just material expense). This rewards crafting investment. Workspace rental still applies if they don't own one.

##### Companion Equipment Wear

> *Proposed addition.* Companions also use equipment that degrades. Currently undefined — addressed in gap analysis below.

#### Subsistence Sinks

##### Lodging

Players need rest to recover HP, Stamina, Focus, and to enable async activities (Training, Crafting). Source: `game_mechanics_npcs.md` (Innkeeper template), `game_mechanics_economy.md`.

| Lodging Quality | Cost/Night | Effect |
|---|---|---|
| Common Room | 1 sp | Long rest. Crowded, noisy. -1 to rest quality roll |
| Private Room | 5 sp | Long rest. Standard quality |
| Fine Room | 15 sp | Long rest. +1 quality. Bonus: 1 temp HP until next rest |

**Estimated drain per session:** 1-15 sp per in-game night spent in town. Often 3-7 nights per typical play arc.

**Player agency:** Camping outdoors is free but forfeits the rest quality bonus and exposes player to encounter risk. The choice is real — gold for safety vs. wilderness for thrift.

##### Food and Drink

Sustained exploration requires rations. Tavern meals are optional but social. Source: `game_mechanics_economy.md`, `game_mechanics_crafting.md`.

| Item | Cost | Notes |
|---|---|---|
| Rations (1 day) | 5 cp | Bare sustenance. Spoils after 2 weeks |
| Tavern meal | 1-2 sp | Social, occasional bonus to rumor-gathering |
| Tavern drink | 1-5 cp | Social lubricant, occasional disposition shift |
| Fresh food (preserved) | 1 sp/day | Better than rations, spoils faster |

**Estimated drain per session:** 1-5 sp on food across a typical multi-day arc.

##### Traveling Merchant Premium

Per `merchant_inventory_restock.md`, traveling merchants charge +10% on purchases. The premium is a sink for players who buy from them rather than seeking out fixed merchants.

**Estimated drain per session:** Variable, based on player purchase choices.

#### Combat Sinks

##### Consumables Used in Combat

Healing potions, oil flasks, alchemical reagents, ammunition. These are purchased and then consumed — value leaves the economy. Source: `game_mechanics_economy.md`, `game_mechanics_crafting.md`.

| Consumable | Cost | Use Frequency |
|---|---|---|
| Minor Healing Potion (2d4+2) | 25 sp | 0-3 per combat-heavy session |
| Antitoxin | 15 sp | Situational (poison encounters) |
| Smelling Salts | 5 sp | Emergency (Fallen ally revival) |
| Anti-Hollow Oil | 10 sp | Hollow encounters |
| Greater Healing Potion (4d4+4) | 75 sp | High-tier emergencies |
| Crossbow bolts (20) | 5 sp | Per ranged combat-heavy day |

**Estimated drain per session:** 25-150 sp for combat-heavy sessions.

##### Death and Resurrection

Death magic requires expensive components. Source: `game_mechanics_combat.md`, `game_mechanics_economy.md`. Note: Mortaen's escalating costs are *non-monetary* (attributes, items, memories, quests) — only the spell components and NPC service fees are gold sinks.

| Mechanism | Cost | Notes |
|---|---|---|
| Revivify diamond | 50 gc (500 sp) | Required component. Diamond consumed. Brings dead character back within 1 minute |
| Resurrection diamond | 500 gc (5,000 sp) | Required component. Diamond consumed. Endgame ritual |
| NPC Resurrection service | 1,000+ sp | Temple service. Cost includes the diamond and the priest's labor |
| Greater Restoration | 200 sp (NPC service) | Cures Hollowed condition. Prevents Hollowed Death |
| Dispel Corruption | 25 sp (NPC service) | Cures Stage 1 Hollowed |
| Cure Poison/Disease | 15 sp (NPC service) | Combat aftermath cleanup |
| Heal Wounds (NPC) | 5 sp | Out-of-combat full heal |
| Remove Curse | 50 sp (NPC service) | Removes specific curses |

**Estimated drain per session:** 0 sp typically; 5-25 sp in moderate combat sessions; 200-1000+ sp during major incidents.

**Player agency:** Cleric/Paladin/Oracle archetypes can self-heal and self-resurrect (eventually), reducing dependence on NPC services. This rewards divine archetype investment.

#### Progression Sinks

##### Mentor Training Fees

Players pay mentors to learn martial variants and ability variants through async Training cycles. Source: `game_mechanics_economy.md`, `game_mechanics_npcs.md`.

| Mentor Tier | Cost Range | Notes |
|---|---|---|
| Frontier exiles, informal | 15-20 sp | Unusual styles from outsiders |
| Standard military/guild | 25-40 sp | Common variant access |
| Elite/specialized | 50-75 sp | Advanced techniques |
| Legendary/master | 80-100 sp | Rare or signature variants |
| Honor-based, quest-gated | 0 sp | Earned through narrative (e.g., Kael Thornridge) |

**Estimated drain per character lifetime:** 200-500 sp across all variants learned. Front-loaded during levels 4-12 when most variants unlock.

##### Faction Donations

Donations grant +1 reputation per 25 sp donated, capped at +3/week and Trusted tier max. Source: `faction_reputation_pricing.md`.

**Estimated drain per session:** 0-75 sp per session for players actively building faction reputation.

##### Faction Bounty Materials

Faction bounties (clearing Hollow nests, delivering supplies) sometimes require player-purchased materials. Source: `faction_reputation_pricing.md`.

**Estimated drain:** Varies. Some bounties net positive (rewards exceed materials); some require investment for reputation gain.

#### Crafting Sinks

##### Crafting Commissions

When the player commissions a blacksmith to craft an item, they pay either with materials (lower fee) or the smith provides everything (higher fee). Source: `game_mechanics_economy.md`, `game_mechanics_npcs.md`.

| Item Tier | Materials Provided | Smith Provides All | Time |
|---|---|---|---|
| Tier 1 | 5 sp | 15 sp | 1 day |
| Tier 2 | 25 sp | 75 sp | 3 days |
| Tier 3 | 100 sp | 300+ sp | 1 week |

**Estimated drain per session:** 25-300 sp for active gear-upgraders. Often single large transactions.

##### Workspace Rental

Players with Crafting skill rent NPC workspaces to craft their own items. Source: `game_mechanics_economy.md`.

| Workspace | Cost/Day | Disposition Discount Available |
|---|---|---|
| Workshop | 2 sp | Friendly: 80%, Trusted: 60% |
| Forge | 5 sp | Friendly: 80%, Trusted: 60% |
| Laboratory | 10 sp | Friendly: 80%, Trusted: 60% |
| Forge + Laboratory | 12 sp | Friendly: 80%, Trusted: 60% |

**Estimated drain per session:** 0-60 sp depending on crafting activity. Active artisan players might spend 30-100+ sp/week on workspace.

**Player agency:** Standing access through quest/relationship completion = free. This rewards relationship investment. Crafting skill investment reduces dependence on commissions (lower long-term cost, higher up-front investment in workspace).

##### Crafting Materials

Materials harvested from creatures are free (combat-as-supply). Materials purchased from merchants are direct sinks. Source: `game_mechanics_crafting.md`.

**Estimated drain:** Highly variable. Some crafters can run entirely on harvested materials; others purchase reagents and ores.

#### Service Sinks

These are NPC services other than healing. Source: `game_mechanics_economy.md`.

| Service | Cost | Frequency |
|---|---|---|
| Identify item | 10 sp | After unusual loot drops |
| Identify Hollow material | 25 sp | Specialist scholars only |
| Research (common) | 15 sp | Quest-relevant info gathering |
| Research (obscure) | 50 sp | Deep lore investigation |
| Translate text | 25 sp | Foreign or ancient documents |

**Estimated drain per session:** 0-50 sp depending on quest content.

**Player agency:** Players with high INT or relevant skills (Arcana, History) can attempt these tasks themselves with skill checks. The NPC service is a "skip the skill check" convenience.

#### Lifestyle Sinks

##### Luxury Goods

Jewelry, fine clothing, exotic imports, decorative items. Mechanically optional — these don't grant combat advantage. Source: `merchant_inventory_restock.md` (Jeweler, Exotic Goods pools).

| Item Type | Cost Range |
|---|---|
| Common gem | 10-25 sp |
| Quality gem | 50-100 sp |
| Rare gem | 200+ sp |
| Quality jewelry | 25-150 sp |
| Exotic imported good | 30-200 sp |

**Estimated drain per session:** 0 typically; 50-500+ sp for players engaging with the lifestyle/social systems.

**Design intent:** Luxury sinks absorb wealth from rich players who don't need more combat gear. The status payoff (NPC reactions, narrative texture) is the reward, not mechanical advantage.

##### NPC Gifts (Disposition Lubrication)

> *Partially specified.* NPCs can be gifted items they value, shifting disposition. Currently informal — addressed in gap analysis below.

##### Tavern Entertainment

Buying rounds of drinks for NPCs, hiring bards, gambling. Source: ad-hoc in `game_mechanics_npcs.md`.

**Estimated drain:** Highly variable, social-context-driven.

#### Endgame Sinks

##### Legendary Item Repair

Per the maintenance sinks above, Legendary items cost 200+ sp to repair. At endgame, this is significant but not crippling.

##### Resurrection Services

For non-Cleric parties, NPC resurrection at 1,000+ sp is a major endgame sink. Source: `game_mechanics_economy.md`.

##### Faction Investments

Per `faction_reputation_pricing.md`, the Merchant Guild offers investments at 100+ sp minimum. These are gold sinks with delayed returns — currently a stub system that needs full mechanical design before implementation.

##### Letter of Credit Interest

5% interest on Merchant Guild credit lines. Source: `faction_reputation_pricing.md`. The 5% is a sink — money paid for the convenience of deferred payment.

##### Consignment Fees

10% commission to merchants who hold items on consignment. Source: `merchant_inventory_restock.md`. Sink for players using high-value sales in low-gold-pool settlements.

##### Warehouse Storage

2 sp/week at Merchant Guild warehouses (Trusted+ access). Source: `faction_reputation_pricing.md`. Recurring sink for players accumulating possessions.

---

### Magnitude Analysis

Estimated gold drained per typical play session, by sink category:

| Category | Low Estimate | Typical | High Estimate | Notes |
|---|---|---|---|---|
| Maintenance | 5 sp | 15 sp | 50 sp | Scales with item tier |
| Subsistence | 5 sp | 15 sp | 75 sp | Scales with lodging quality |
| Combat | 0 sp | 50 sp | 1,000+ sp | Spikes on death |
| Progression | 0 sp | 25 sp | 100 sp | Front-loaded mid-level |
| Crafting | 0 sp | 30 sp | 300 sp | Active artisans only |
| Service | 0 sp | 15 sp | 100 sp | Quest-driven |
| Lifestyle | 0 sp | 0 sp | 500+ sp | Player-expression-driven |
| Endgame | 0 sp | 0 sp | 5,000+ sp | High-level player only |
| **Total typical** | **~10 sp** | **~150 sp** | **~7,000+ sp** | Per session |

**Faucet/sink balance check:** Quest reward tiers (per `game_mechanics_economy.md`) are 25-50 sp (Tier 1), 100-250 sp (Tier 2), 300-700 sp (Tier 3). A typical session yields 1-2 quest completions plus loot/material sales (~100-300 sp). With typical sink drain of ~150 sp, a session yields net positive ~50-150 sp. This is the desired balance — players accumulate wealth slowly through play, with bursts of high-value endgame sinks (resurrection, faction investments) providing wealth absorption for endgame players.

---

### Gap Analysis & Proposed Additions

The existing sinks cover most natural gameplay loops, but a few gaps exist:

#### Gap 1: Companion Equipment Maintenance

**Problem:** Companions use equipment in combat, but no rules govern its degradation or repair. If companions never need gear maintenance, the player has a free combat partner with no upkeep — economically unrealistic and missing a sink opportunity.

**Proposal:** Companion equipment degrades on the same schedule as player gear. Repair cost is half of equivalent player gear (companions use simpler equipment). The companion's gear quality is set narratively (Kael's longsword, Lira's bow, etc.) and can be upgraded by the player at standard commission cost.

**Sink magnitude:** ~5-25 sp per session for companion upkeep at typical play. Adds to Maintenance category.

#### Gap 2: Bribery System

**Problem:** Social challenges currently resolve through Persuasion / Deception / Intimidation skill checks. There's no formal mechanism for *paying* an NPC to reveal information, look the other way, or grant access. This is a missed gold sink that's also a missed gameplay mechanic.

**Proposal:** Bribery as an alternative resolution path for social challenges. Player offers gold; NPC's accept threshold is determined by:
- NPC role (corrupt guard accepts low; honorable noble doesn't accept any)
- Disposition (Friendly NPCs may accept smaller bribes; Hostile may not accept any)
- Faction loyalty (Honored faction members refuse bribes that betray faction)
- Stakes of the request (small favors: 5-25 sp; significant betrayals: 100+ sp)

If accepted, the bribe replaces the skill check. If refused, the player has revealed their willingness to bribe — minor disposition penalty for the gamble.

**Sink magnitude:** Variable. Players who use bribery as a primary tactic might spend 50-200+ sp per session. Adds to Service or Progression category.

#### Gap 3: Travel Tolls

**Problem:** Geographic travel is currently free. In a world with faction-controlled territories, ferries, mountain passes, and policed cities, this is a missed worldbuilding and economic opportunity.

**Proposal:** Selective travel tolls at key infrastructure points:
- Ferry crossings: 5 sp/person (player + companion = 10 sp). Free if Friendly+ with controlling faction.
- Bridge tolls: 1-5 sp at key bridges in faction-controlled territory.
- City entry tolls: 5 sp at major cities (one-time per visit). Waived for faction members, citizens, escorted persons.
- Mountain pass guides: 25 sp for safe passage through dangerous terrain. Can attempt without guide (Survival check, encounter risk).

**Sink magnitude:** 10-50 sp per session for cross-region travel. Avoidable through alternative routes (longer travel time) or faction relationships (waived tolls). Adds to Subsistence category.

**Important constraint:** Tolls must always have a free alternative (long route, low-disposition relationship, skill check). Otherwise they become pure taxation, which violates the design philosophy.

#### Gap 4: Property and Housing

**Problem:** The GDD mentions "property" as a possible significant wealth category but no mechanics exist. For Phase 1 (single-player), property may not be needed. For Phase 2+ (multiplayer/MMO), it becomes critical for endgame wealth absorption.

**Proposal (Phase 2+ stub):** Property purchase, maintenance, and upgrade as a major endgame sink:
- Cottage: 500 sp purchase, 5 sp/week maintenance.
- Townhouse: 2,000 sp purchase, 20 sp/week.
- Estate: 10,000 sp purchase, 100 sp/week.
- Upgrades: workshop addition (200 sp), forge addition (500 sp), magical wards (1,000+ sp).

**For Phase 1:** Defer. Add to "Future Systems" notes for Phase 2+ implementation.

#### Gap 5: NPC Gift System

**Problem:** Players can shift NPC disposition through actions, but no formal mechanic exists for *gifting* items to NPCs. This is referenced informally in worldbuilding but not specified.

**Proposal:** NPCs have an `appreciated_gifts` field listing items they value (favorite drinks, rare materials they need, items related to their backstory). Gifting an appreciated item shifts disposition by +1 to +3 depending on rarity and personal significance. Generic gifts (common food, basic gear) shift disposition by +0 or +1 if they're useful to that NPC's role.

The sink occurs because gift items have value the player chose to forfeit (gave away instead of selling).

**Sink magnitude:** 10-100 sp per session for relationship-focused players. Adds to Lifestyle or Progression category.

---

### Implementation Notes

#### Tracking Sinks

The economy simulation needs to track currency removed from the player economy at each sink event. This data is used for:

1. **Inflation analysis** (per the next section, Inflation Controls): comparing total faucet output vs. sink drain over time.
2. **Player analytics** (post-launch): identifying which sinks see the most/least usage to detect balance issues.
3. **Narrative consequences** (god-agent simulation): excessive death spending might draw Mortaen's attention; excessive luxury spending might shift faction perceptions.

#### Sink Event Logging

Every time gold leaves the player economy, the rules engine logs:

```python
{
  "player_id": "player_xyz",
  "sink_category": "combat",
  "sink_type": "consumable_used",
  "item_id": "minor_healing_potion",
  "amount_sp": 25,
  "context": "combat_with_mawling_pack",
  "timestamp": 1736896000
}
```

Aggregated by category, this produces the player's economic profile and the world's overall sink rate.

---

### Design Decisions

> Extracted to `game_mechanics_decisions.md` for canonical reference.

**Decision 105: Gold sinks fall into eight categories with distinct design intents.** Reason: the categorization (Maintenance/Subsistence/Combat/Progression/Crafting/Service/Lifestyle/Endgame) ensures each sink serves a clear purpose and that the sink ecosystem is balanced. Without categorization, sinks tend to cluster in one area (combat consumables, for example) leaving other player activities economically inert. The category framework also makes gap analysis easier — if no Lifestyle sinks exist, that's a clear design issue.

**Decision 106: All forced sinks must have player-agency mitigations.** Reason: forced sinks the player can't avoid become punitive taxation. Item repair is forced (durability is real) but mitigated by Crafting skill (self-repair). Death is forced (combat happens) but mitigated by archetype choice (divine archetypes self-resurrect) and gameplay (avoid dying). Subsistence is forced (you must rest) but mitigated by camping (free, riskier). Every "forced" sink in the ledger has at least one mitigation path, preserving player choice.

**Decision 107: Mortaen's death costs are non-monetary; gold sinks for death come from spell components and NPC services.** Reason: the death system's narrative weight comes from attribute loss, item loss, and memory fragments — things the player can't simply spend gold to recover. Making death a *gold* sink would convert a profound narrative system into an economic transaction. Keep them separate: Mortaen's domain extracts narrative cost; resurrection magic extracts gold cost. Both can apply to the same death (you spend 50 gc on Revivify *and* still see Mortaen if it doesn't take effect in time).

**Decision 108: Endgame sinks must absorb wealth at high magnitudes (1,000+ sp).** Reason: at high levels, players accumulate wealth faster than mid-game sinks can absorb. Without endgame sinks, gold becomes meaningless to high-level players. Resurrection services (1,000+ sp), legendary repair (200+ sp), faction investments (100+ sp minimum), and property maintenance (Phase 2+) all serve as wealth absorbers for the post-mid-game economy. The 3.0× price ceiling from the supply/demand engine ensures these costs don't escape into pathological territory.

**Decision 109: Lifestyle sinks reward wealth without granting mechanical advantage.** Reason: the player should be able to spend money on status, identity, and roleplay without affecting combat balance. Fine clothing, jewelry, and exotic goods absorb wealth from rich players who don't need more combat gear. The reward is narrative — NPCs notice the player is well-dressed, the DM describes their entrance with weight, certain social interactions become easier. This separates "I have the best gear" (combat power) from "I am rich" (status and roleplay), which lets both be progression axes without one dominating.

**Decision 110: Travel tolls must always have a free alternative.** Reason: tolls are a useful sink and worldbuilding tool, but pure taxation violates the design philosophy. Every toll point in the world should have an alternative: longer routes, faction relationship that waives the toll, or a skill check (Survival, Stealth) to bypass. This preserves player agency — the toll becomes "the convenient option" rather than "the only option."

**Decision 111: Bribery is a real social mechanic, not just a thematic option.** Reason: in a world with corrupt officials, desperate guards, and grey morality, players should be able to use gold to influence outcomes. The skill-check alternative remains (Persuasion, Deception, Intimidation), but bribery offers a wealth-conversion path: spend money to skip a check. This makes gold relevant to social play, not just combat/crafting/services. The refusal mechanic (NPC declines, minor disposition penalty) ensures bribery isn't risk-free — corrupt NPCs accept; honorable ones don't.

**Decision 112: Companion equipment maintenance is half player gear cost.** Reason: companions in combat take damage and use equipment, but charging full repair cost would double the maintenance burden on the player. Halving it acknowledges that companions use simpler gear (Kael's longsword is functional, not masterwork) while still creating a real sink. This also opens companion gear upgrades as a meaningful gold sink — the player can invest in better companion equipment for tactical benefit.

**Decision 113: Sink event logging is required infrastructure for inflation control.** Reason: without per-sink tracking, balance analysis is impossible. The aggregated sink data feeds inflation control (next section), live balance monitoring, and narrative systems (god-agent attention to player spending patterns). The implementation cost is minor (one log entry per sink event); the analytical value is significant.
