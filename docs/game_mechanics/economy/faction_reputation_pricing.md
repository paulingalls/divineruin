# Faction Reputation Pricing — Economy Section

> **Integration note:** This section replaces the "Faction Reputation Pricing" stub in `game_mechanics_economy.md` under "Systems Not Yet Specified." It also completes the TODO in the Merchant Pricing Formula section ("Define faction reputation tiers and their specific price modifiers"). Cross-references: `world_data_simulation.md` (faction schema, reputation tiers), `game_mechanics_encounter_roles.md` (material sell values), `game_mechanics_npcs.md` (merchant subtypes).

---

## Faction Reputation Pricing

### Reputation Tiers and Price Modifiers

Faction reputation affects prices at all merchants affiliated with that faction. Modifiers are smaller than disposition modifiers — faction is an organizational stance, not a personal relationship. A merchant who personally likes you gives a bigger discount than one following faction policy. But the two stack.

| Faction Tier | Threshold | Price Modifier |
|---|---|---|
| Hostile | -10 | Refuses service. No trade possible |
| Unfriendly | -5 | +15% |
| Neutral | 0 | 1.0× (no modifier) |
| Friendly | +5 | -5% |
| Trusted | +15 | -10% |
| Honored | +25 | -15% |

### Combined Pricing Formula

Disposition and faction reputation stack multiplicatively:

```
final_price = base_price × disposition_modifier × faction_modifier
```

**Modifier Reference (combined):**

| | Hostile Faction | Unfriendly Faction | Neutral Faction | Friendly Faction | Trusted Faction | Honored Faction |
|---|---|---|---|---|---|---|
| **Hostile Disposition** | No service | No service | +20% | +14% | +8% | +2% |
| **Unfriendly Disposition** | No service | +26.5% | +10% | +4.5% | -1% | -6.5% |
| **Neutral Disposition** | No service | +15% | 1.0× | -5% | -10% | -15% |
| **Friendly Disposition** | No service | +3.5% | -10% | -14.5% | -19% | -23.5% |
| **Trusted Disposition** | No service | -8% | -20% | -24% | -28% | -32% |

**Key price points:**

- **Worst tradeable case:** Unfriendly disposition + Unfriendly faction = 1.265× (paying 26.5% more). Painful but not prohibitive — the player can still gear up, they're just overpaying.
- **Neutral baseline:** Neutral + Neutral = 1.0×. This is where most merchants start for a new player.
- **Good standing:** Friendly disposition + Friendly faction = 0.855× (14.5% discount). A solid reward for investing in relationships.
- **Best possible case:** Trusted disposition + Honored faction = 0.68× (32% discount). Requires deep investment in both personal and organizational standing. A player at this level has spent real time building this relationship — the 32% discount is earned.

### Faction Service Refusal

At Hostile faction reputation, all affiliated merchants refuse service regardless of personal disposition. Even a merchant who personally likes the player won't risk their faction standing by trading with a known enemy.

At Unfriendly faction reputation, merchants provide basic goods only. Specialized services (identify, research, custom commissions, rare inventory) are unavailable until the player reaches Neutral.

| Faction Tier | Services Available |
|---|---|
| Hostile | None. Merchant refuses all interaction. May report player's location to faction authorities |
| Unfriendly | Basic goods only (rations, common supplies, standard weapons/armor). No services. No rare inventory |
| Neutral | Full standard inventory and services |
| Friendly | Standard inventory + faction-discounted supplies (see Faction-Exclusive Access below) |
| Trusted | Full inventory including restricted/faction-specific items and services |
| Honored | Everything, plus priority access (restocked items reserved for Honored buyers first) |

---

### Earning Reputation Through Economic Activity

Economic activity alone doesn't shift faction reputation — buying rations at a Thornwatch outpost doesn't make you a Thornwatch ally. Reputation is primarily earned through quests, narrative choices, and world actions (as defined in the faction schema in `world_data_simulation.md`).

However, specific **meaningful economic contributions** to a faction's mission grant small reputation bonuses. These are targeted actions that demonstrate alignment with the faction's values, not simple purchase volume.

#### Reputation-Granting Economic Actions

| Action | Reputation Gain | Conditions | Narrative Logic |
|---|---|---|---|
| **Sell rare materials to faction scholars/specialists** | +1 per transaction | Material must be Tier 2+ and relevant to the faction's interests | Contributing to the faction's research or military capability |
| **Commission faction-specific equipment** | +1 per commission | Must be Tier 2+ commission (25+ sp) | Investing in the faction's craft economy |
| **Donate to faction temple or cause** | +1 per 25 sp donated | Must be a recognized donation point (temple, war fund, relief effort) | Direct financial support of the faction's mission |
| **Fulfill faction bounties** | +1 to +3 per bounty | Bounties are standing tasks, not full quests | Ongoing service (clearing Hollow nests, delivering supplies, scouting) |
| **Supply rare crafted goods** | +2 per item | Player-crafted Tier 2+ items sold to faction quartermaster | Supplying the faction with something they can't easily get elsewhere |

**Caps and cooldowns:**

- Maximum +3 reputation per faction per real-time week from economic activity alone. This prevents reputation grinding through bulk selling or donation spam.
- Each specific action type can only grant reputation once per real-time day. Selling five venom sacs to the same Thornwatch alchemist in one visit is one +1, not five.
- Economic reputation gains cannot push a player past the Trusted threshold (+15). Reaching Honored (+25) requires quest completion and narrative commitment — you can't buy your way to the top.

**The cap at Trusted is important.** It means economic activity is a *supplement* to relationship building, not a replacement. A player who trades regularly with the Thornwatch while also completing their missions reaches Trusted faster. A player who only trades never reaches Honored. This preserves the narrative weight of the highest tier.

#### Reputation-Damaging Economic Actions

| Action | Reputation Loss | Conditions |
|---|---|---|
| **Sell faction secrets or intelligence to rivals** | -3 to -5 | Detected by faction (Insight/Investigation check by faction NPCs) |
| **Trade restricted faction materials to outsiders** | -2 per incident | Faction-exclusive items sold to non-faction merchants |
| **Fence stolen faction goods** | -3 per incident | Caught dealing in goods marked with faction identifiers |
| **Refuse a faction bounty after accepting** | -1 per refusal | Backing out of a committed task |
| **Undercut faction merchants** | -1 per incident | Selling identical goods at lower prices in faction territory (Phase 2+ multiplayer only) |

**Detection is not guaranteed.** Most negative actions only trigger reputation loss if the faction discovers them. A Spy who sells Thornwatch patrol routes to a rival faction only loses reputation if they're caught — but the risk is always present. NPCs with Insight proficiency may detect deception during trade interactions, and faction intelligence networks may uncover patterns over time (resolved by the simulation tick).

---

### Faction-Exclusive Access

Higher faction reputation unlocks access to items and services that aren't available on the open market. These are organized by tier to provide clear progression rewards.

#### Access Framework

| Faction Tier | Unlocks |
|---|---|
| **Neutral** | Standard merchant inventory. No faction-specific access |
| **Friendly** | Faction-discounted consumables (healing supplies, rations, basic ammunition at an additional -10% beyond normal faction pricing). Access to faction bounty board |
| **Trusted** | Faction-specific equipment (weapons, armor, tools bearing the faction's mark). Faction crafting commissions (NPC smiths will make faction-recipe items). Access to faction workspace at standing access rates |
| **Honored** | Priority restocking (when merchant inventory is limited, Honored buyers get first access). Faction masterwork commissions (highest-tier NPC crafting). Access to faction intelligence (maps, threat assessments, classified information sold as a service) |

#### Example: Thornwatch Faction Access

| Tier | Items/Services Available | Price |
|---|---|---|
| Friendly | Thornwatch rations (standard rations + 1 day shelf life), signal arrows, basic anti-Hollow oil (1d4 bonus radiant damage, 3 uses) | Standard prices with faction discount |
| Trusted | Thornwatch-issue armor (chain shirt with +1 vs Hollow necrotic, cosmetic faction markings), Thornwatch blade (longsword, +1 damage vs Hollow), patrol maps (reveal Hollow corruption levels in a region) | 1.5× base item price (faction mark-up for specialty gear) |
| Honored | Thornwatch command seal (grants authority over rank-and-file Thornwatch soldiers in the field), classified intelligence reports (current Hollow movement patterns, Named creature sightings), priority access to Thornwatch forge | Intelligence: 50 sp per report. Seal: quest-granted, not purchased |

#### Example: Merchant Guild Faction Access

| Tier | Items/Services Available | Price |
|---|---|---|
| Friendly | Trade route information (which towns have what in stock), market forecasts (upcoming supply/demand shifts — useful for planning what to craft), caravan escort bounties | Information: 5 sp. Bounties: standard quest rewards |
| Trusted | Bulk discount on common goods (additional -10% when buying 10+ of same item), access to guild warehouses (store items between sessions, 2 sp/week), guild letter of credit (spend up to 50 sp in any guild-affiliated town, repay later) | Warehouse: 2 sp/week. Credit: 5% interest |
| Honored | Auction access (rare items sold by guild to highest bidder — unique inventory not available elsewhere), trade monopoly rights in a specific settlement (exclusive selling rights for one item category, Phase 2+ multiplayer), guild investment opportunities (spend gold now, receive returns over time — a gold sink with delayed payoff) | Auction: varies. Investments: 100+ sp minimum |

**Faction access is a framework, not an exhaustive list.** Each faction's specific inventory is authored as part of that faction's content design. The framework defines *what tiers unlock* and *the pattern of progression* — the specific items are faction-dependent and may evolve with seasonal content.

---

### Interaction with Other Economy Systems

**Workspace rental:** Faction reputation stacks with disposition for workspace access. A player who is Trusted with a blacksmith's faction gets the standing access benefit (free workspace use) more easily — the faction reputation contributes to the relationship that makes standing access possible.

**Crafting commissions:** NPC smiths in faction territory use faction pricing for commissions. A Thornwatch-affiliated blacksmith charges Trusted players 10% less for commissions (on top of any disposition discount).

**Merchant inventory:** Faction reputation affects *what* a merchant stocks, not just prices. At higher tiers, merchants reveal inventory they don't show to outsiders. The DM narrates this naturally: "You've been good to the Watch. There's something in the back I don't show most people — interested?"

**Supply and demand:** Faction-controlled trade routes affect regional supply. If a faction's territory is disrupted (Hollow incursion, war), their merchants' inventory shrinks and prices rise. Players with high faction reputation may receive priority access to scarce goods during shortages (Honored tier benefit).

---

### DM Narration Guidance

Faction pricing is invisible math — the player never hears "your faction modifier is 0.9." The DM conveys pricing through dialogue and context.

**Neutral faction standing:**
> "Grimjaw looks you over. Standard rates — nothing more, nothing less. He doesn't know you."

**Friendly faction standing:**
> "When Grimjaw sees the Thornwatch badge on your pack, his expression warms. 'Friend of the Watch, eh? I can do a little better on price for you.'"

**Trusted faction standing:**
> "Grimjaw nods when you walk in — he knows your face. 'Got something in the back you might want to see. Not for everyone, but you've earned it.'"

**Honored faction standing:**
> "'I set aside the good steel when I heard you were in town. First pick, before the regular stock goes out. The Watch takes care of its own.'"

**Unfriendly faction standing:**
> "Grimjaw's expression cools when he sees you. 'I'll sell you what you need. Basic goods. Don't ask for more.'"

**Reputation gain through economic activity:**
> After selling Hollow materials to a Thornwatch scholar: "Word gets around that you've been supplying the Watch with research materials. The next Thornwatch patrol you meet is a shade friendlier."

The reputation shift is narrated as *consequence*, not transaction. The player doesn't hear "+1 Thornwatch reputation." They hear the world treating them differently.

---

### Design Decisions

> Extracted to `game_mechanics_decisions.md` for canonical reference.

**Decision 82: Faction price modifiers are smaller than disposition modifiers.** Reason: disposition represents a personal relationship — a merchant who trusts you gives you a better deal because they know and like you. Faction reputation is institutional policy — the merchant follows the rules their organization sets. Personal relationships should always be more impactful than bureaucratic standing because this is a game about human connection, not organizational management. The multiplicative stacking ensures both matter without either dominating.

**Decision 83: Economic activity grants reputation only through meaningful contributions, not purchase volume.** Reason: if buying rations shifted reputation, the system collapses into "spend money to get discounts to spend less money" — a pure economic loop with no narrative content. By limiting reputation-granting actions to meaningful contributions (selling rare materials, donating, fulfilling bounties), the system ties economic behavior to story. You earn the Thornwatch's respect by supplying what they need, not by shopping at their stores.

**Decision 84: Economic reputation gains cap at Trusted (+15), not Honored (+25).** Reason: Honored represents deep narrative commitment — command authority, classified intelligence, the faction treats you as one of their own. That level of trust cannot be purchased. It requires quest completion, difficult choices, and demonstrated loyalty. Allowing economic activity to reach Honored would cheapen the narrative weight of the highest tier and create a pay-to-win dynamic. The cap at Trusted means economic contributions *supplement* the relationship but can never *replace* it.

**Decision 85: Faction-exclusive items use a tiered access framework, not exhaustive catalogs.** Reason: exhaustive per-faction catalogs would be enormous and would lock content design too early. The framework defines the *pattern* (what each tier unlocks categorically) while leaving specific items to faction content authoring. This means new factions can be added without modifying the economy system — they just populate their tier slots. The Thornwatch and Merchant Guild examples demonstrate the pattern; other factions follow the same structure.

**Decision 86: Detection gates negative reputation from economic activity.** Reason: if every negative economic action automatically triggered reputation loss, stealth-oriented archetypes (Spy, Rogue) would be disproportionately punished for their core gameplay loop. By gating negative consequences behind detection, the system creates risk-reward tension: selling stolen Thornwatch goods is profitable but dangerous. Getting caught is devastating. This makes the Spy's Deception skill economically valuable — they can play both sides if they're skilled enough — while ensuring consequences exist for those who aren't.
