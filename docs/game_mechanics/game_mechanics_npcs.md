# Divine Ruin — Game Mechanics: NPC Framework & Mentor Registry

> **Claude Code directive:** Read `game_mechanics_core.md` first for foundational systems. This document defines NPC role archetypes, combat stat blocks for humanoid NPCs, the mentor registry for the martial variant system, and settlement population templates.
>
> **Related docs:** `game_mechanics_core.md` (required), `game_mechanics_archetypes.md` (mentor-style system, archetype abilities), `game_mechanics_bestiary.md` (creature schema — NPCs extend this), `game_mechanics_magic.md` (caster NPC spells)
>
> **Also see:** The GDD's NPC Design section and `world_data_simulation.md` for Tier 1/2 NPC categories, disposition mechanics, voice profiles, schedules, and gated knowledge systems. This document adds the *mechanical* layer — combat stats, role templates, and mentor data — on top of those narrative systems.

---

## NPC Schema

NPCs extend the creature stat block from `game_mechanics_bestiary.md` with additional fields for social interaction, economy, and world simulation. Every NPC that can enter combat uses the creature stat block for resolution. Every NPC that can be spoken to uses the NPC extension fields.

### Schema Extension (on top of CreatureStatBlock)

```python
class NPCStatBlock(CreatureStatBlock):
    # === NPC IDENTITY ===
    npc_tier: int                # 1 = authored (rich data), 2 = template-generated (tags only)
    role: str                    # "merchant" | "guard" | "blacksmith" | "innkeeper" | etc.
    role_archetype: str          # Links to Role Archetype Template
    species: str                 # "human" | "elari" | "vaelti" | "korath" | "draethar" | "thessyn"
    gender: str
    age_range: str               # "young" | "middle" | "elder"
    
    # === PERSONALITY (Tier 1: rich, Tier 2: tags only) ===
    personality: list[str]       # ["gruff", "practical", "secretly kind"]
    speech_style: str            # "formal", "colloquial", "terse", "flowery"
    mannerisms: list[str]        # Verbal tics, habitual actions
    backstory_summary: str       # Motivations and history (Tier 1 only)
    
    # === SOCIAL ===
    faction: str                 # Faction ID: "thornwatch", "merchant_guild", etc.
    default_disposition: str     # "hostile" | "unfriendly" | "neutral" | "friendly" | "trusted"
    disposition_modifiers: dict  # {"helped_with_task": 2, "threatened": -5}
    knowledge: dict              # Gated information by disposition level
    secrets: list[str]           # Things this NPC knows but won't share easily
    
    # === SCHEDULE ===
    schedule: dict[str, str]     # {"06:00-20:00": "market_square", "20:00-06:00": "home"}
    
    # === ECONOMY ===
    inventory_pool: str | None   # Links to inventory template: "weapons_common", "alchemical_supplies"
    services: list[str]          # What this NPC offers: ["buy", "sell", "repair", "train", "heal"]
    price_modifier: float        # 1.0 = standard. Adjusted by disposition and faction rep
    
    # === MENTOR (null if not a mentor) ===
    mentor: {
        technique: str           # Which base technique they teach variant for
        variant_name: str        # Style variant name
        variant_effect: str      # Mechanical modification
        training_cycles: int     # Async cycles to learn (typically 3-4)
        requirements: dict       # {"disposition": "friendly", "quest": "prove_yourself", "gold": 50}
        narration_cue: str       # How DM describes the training
    } | None
    
    # === VOICE ===
    voice_id: str                # TTS voice profile
    voice_notes: str             # Performance notes for DM: "deep, slow, Keldaran accent"
```

---

## Role Archetype Templates

Role archetypes are reusable templates that define what an NPC of a given role looks like mechanically. When the world simulation needs "a blacksmith in this settlement," it instantiates from the template, adds personality tags, and the NPC is functional.

Each template defines: default combat stats (if relevant), services offered, typical inventory, knowledge domains, and disposition baseline.

### Civilian Roles (Non-Combat by Default)

---

#### Merchant

> *Buys and sells goods. The player's primary interface with the material economy.*

**Combat:** Avoids combat. If cornered, fights as Commoner (Level 1, HP 6, AC 10). Calls for guards.
**Services:** Buy, sell. Some specialists also identify or appraise items.
**Inventory pool:** Varies by subtype — see Merchant Subtypes below.
**Default disposition:** Neutral (adjusts toward friendly with repeated purchases).
**Knowledge domains:** Market gossip, trade route conditions, item properties, regional supply/demand.
**Price modifier:** 1.0 baseline. Friendly: 0.9. Trusted: 0.8. Unfriendly: 1.2. Hostile: refuses service.

**Merchant Subtypes:**

| Subtype | Inventory Pool | Special Services | Typical Location |
|---|---|---|---|
| General Goods | Common supplies, rations, rope, torches, tools | — | Every settlement |
| Weapons & Armor | Martial weapons, shields, armor (quality scales with settlement size) | Repair (Crafting: Trained) | Towns and cities |
| Alchemist | Potions, reagents, poisons (gated by disposition), herbs | Identify potions, create custom mixtures (Crafting: Expert) | Towns and cities |
| Jeweler | Gems, jewelry, precious metals, enchanted trinkets | Appraise (identify gem/jewelry value), buy gems at fair price | Cities only |
| Exotic Goods | Rare materials, imports, Hollow-sourced materials (purified), cultural items | Appraise exotic items, connect to specialist buyers | Cities, major trade routes |
| Traveling Merchant | Mixed common + 1-2 rare items. Changes stock between visits | Rumors from the road (free knowledge) | Roads, trade routes, arrives in settlements periodically |
| Black Market | Restricted items, stolen goods, tainted Hollow materials (unpurified), poisons | Fence stolen items, no questions asked. Requires trust | Cities (hidden), certain taverns |

---

#### Blacksmith

> *Crafts and repairs weapons and armor. The player's interface with the equipment maintenance system.*

**Combat:** Can fight if settlement threatened. Uses Militia template (Level 2, HP 14, AC 11).
**Services:** Repair equipment, craft basic weapons/armor (Tier 1-2), upgrade items (if Expert+ Crafting). Accepts crafting commissions with materials provided by player.
**Inventory pool:** Basic weapons, basic armor, tools, repair supplies.
**Default disposition:** Neutral.
**Knowledge domains:** Weapon/armor properties, material quality, local military situation, Keldaran forge techniques (if Keldaran).
**Special:** Blacksmiths with Expert Crafting can craft Tier 2 equipment. Master Crafting (rare, usually only in cities or Keldaran holds) can craft Tier 3.

**Crafting Commission Pricing:**

| Item Tier | Base Cost (materials provided) | Base Cost (smith provides materials) | Time |
|---|---|---|---|
| 1 | 5 sp | 15 sp | 1 day |
| 2 | 25 sp | 75 sp | 3 days |
| 3 | 100 sp | 300+ sp | 1 week |

---

#### Innkeeper

> *Provides rest, food, drink, and gossip. The social hub of every settlement.*

**Combat:** Non-combatant. Calls for guards or hides. May have a bouncer (Guard stat block).
**Services:** Lodging (enables long rest in settlements), food/drink, rumors, message board (quest hooks), introduce NPCs.
**Inventory pool:** Food, drink, basic supplies.
**Default disposition:** Friendly (innkeepers are naturally welcoming — it's their business).
**Knowledge domains:** Local gossip, visitor logs (who's been through town), regional events, NPC locations ("the blacksmith? She's usually at the forge until sundown").
**Special:** Innkeepers are the DM's natural exposition vehicle. Their "rumors" knowledge pool is seeded by the world simulation with current events, quest hooks, and regional news.

**Lodging Pricing:**

| Quality | Cost/Night | Effect |
|---|---|---|
| Common room | 1 sp | Long rest. Crowded, noisy. -1 to rest quality roll |
| Private room | 5 sp | Long rest. Standard quality |
| Fine room | 15 sp | Long rest. +1 to rest quality roll. Bonus: 1 temp HP until next rest |

---

#### Healer / Temple Attendant

> *Provides healing services and divine counsel. The player's interface with the divine economy.*

**Combat:** Can fight as Acolyte (Level 2, HP 12, AC 12, Sacred Flame cantrip + Heal Wounds 2/day).
**Services:** Heal HP (for gold), cure conditions, remove curses (higher level only), purify Hollow materials (Dispel Corruption), resurrection services (extremely expensive, city temples only).
**Inventory pool:** Healing supplies, holy water, blessed oil, prayer beads.
**Default disposition:** Friendly (temples serve all).
**Knowledge domains:** Patron god's domain, religious history, Hollow corruption symptoms, theological disputes, divine favor guidance.
**Special:** Healer NPCs are associated with a specific god. Their services and knowledge are patron-themed. An Orenthel healer offers different counsel than a Mortaen priest.

**Healing Pricing:**

| Service | Cost | Requirements |
|---|---|---|
| Heal Wounds (1d8+WIS) | 5 sp | — |
| Cure Poison/Disease | 15 sp | — |
| Dispel Corruption (purify material) | 25 sp | Temple of Orenthel, Kaelen, or Valdris |
| Remove Curse | 50 sp | City temple only |
| Greater Restoration | 200 sp | City temple, high-level priest |
| Resurrection | 1000+ sp | Cathedral only, patron approval |

---

#### Scholar / Sage

> *Provides information, research, and identification services. The player's interface with the knowledge economy.*

**Combat:** Non-combatant. Flees immediately.
**Services:** Identify items (magical properties, history, value), research topics (takes 1-3 days, costs gold), translate texts, appraise Hollow materials, buy research samples.
**Inventory pool:** Scrolls, books, writing supplies, research tools.
**Default disposition:** Cautious (scholars protect their knowledge).
**Knowledge domains:** Varies by specialty — Aelindran history, Hollow taxonomy, magical theory, ancient languages, regional geography, creature lore.
**Special:** Scholars are the primary buyer of Hollow research materials. They pay premium prices for Named fragments, spatial residue, and remnant identities.

**Research Pricing:**

| Service | Cost | Time |
|---|---|---|
| Identify item | 10 sp | Immediate |
| Identify Hollow material | 25 sp | 1 day |
| Research topic (common) | 15 sp | 1 day |
| Research topic (obscure) | 50 sp | 3 days |
| Translate text | 25 sp | 1-3 days depending on length |
| Buy Hollow research sample | 50-500 sp depending on tier | Immediate (they pay you) |

---

#### Quest Giver

> *Not a standalone role — a function layered onto any NPC role. Any NPC can give quests based on their role and knowledge.*

Quest giving is driven by the NPC's `knowledge` gating system. An innkeeper with high disposition shares a rumor that becomes a quest. A blacksmith who needs rare materials offers a commission that requires dungeon delving. A scholar researching the Hollow asks the player to retrieve samples.

**Common quest sources by role:**

| Role | Quest Types |
|---|---|
| Merchant | Escort shipment, recover stolen goods, source rare materials |
| Blacksmith | Find rare materials, clear a mine, test new weapon in field |
| Innkeeper | Investigate missing traveler, deal with road bandits, deliver message |
| Healer | Clear corruption from sacred site, retrieve healing herbs, rescue sick person |
| Scholar | Retrieve artifact, investigate ruins, bring Hollow samples |
| Guard Captain | Clear bandit camp, patrol dangerous route, investigate disturbance |
| Faction Leader | Faction-specific missions, political tasks, territory defense |

---

### Military / Combat Roles

---

#### Guard

> *Settlement law enforcement. First responders to threats.*

**Level:** 2 | **HP:** 16 | **AC:** 14 (chain shirt + shield) | **Speed:** 30 ft
**STR** 14 (+2) **DEX** 12 (+1) **CON** 12 (+1) **INT** 10 (+0) **WIS** 10 (+0) **CHA** 10 (+0)
**Save Prof:** STR | **XP:** 50

**Attacks:**
| Name | Type | Reach | Hit | Damage | Special |
|---|---|---|---|---|---|
| Spear | Melee | 5 ft | +4 | 1d6+2 piercing | Can throw: 20/60 ft |
| Crossbow | Ranged | 80 ft | +3 | 1d8+1 piercing | — |

**Passives:** Alert (advantage on initiative, can't be surprised while on duty).
**Services:** Directions, warnings about local dangers, arrest criminals, respond to threats.
**Default disposition:** Neutral. Shifts to friendly if player has positive faction rep with the settlement's controlling faction.
**Knowledge:** Local laws, recent incidents, patrol routes, settlement layout, wanted persons.

**Variant — Elite Guard (Tier 2):**
**Level:** 4 | **HP:** 32 | **AC:** 16 (half plate + shield) | +6 to hit, 1d8+3 damage. Multiattack (2 strikes). Stationed at important locations (gates, faction HQs, noble districts).

---

#### Soldier (Ashmark)

> *Frontline defender against the Hollow. Battle-hardened.*

**Level:** 3 | **HP:** 24 | **AC:** 15 (chain mail + shield) | **Speed:** 30 ft
**STR** 14 (+2) **DEX** 12 (+1) **CON** 14 (+2) **INT** 10 (+0) **WIS** 12 (+1) **CHA** 10 (+0)
**Save Prof:** STR, CON | **XP:** 75

**Attacks:**
| Name | Type | Reach | Hit | Damage | Special |
|---|---|---|---|---|---|
| Longsword | Melee | 5 ft | +4 | 1d8+2 slashing | — |
| Javelin | Ranged | 30/120 ft | +4 | 1d6+2 piercing | — |

**Passives:** Hollow Veteran (advantage on saves vs Frightened from Hollow sources). Formation Fighter (+1 AC when adjacent to another soldier).
**Actives:** Rally (1/encounter) — all allied soldiers within 30 ft gain +1 to attacks for 2 rounds.
**Knowledge:** Hollow creature behavior, Ashmark tactical situation, supply routes, corruption signs.

**Variant — Ashmark Sergeant (Tier 2):**
**Level:** 5 | **HP:** 40 | **AC:** 16 | +6 to hit, 1d8+3 damage. Multiattack (2 strikes). Leadership Aura (+1 attacks for allies in 30 ft). Carries blessed weapon (+1d4 radiant vs Hollow).

**Variant — Ashmark Commander (Tier 3):**
**Level:** 9 | **HP:** 75 | **AC:** 18 (plate + shield) | +8 to hit, 1d10+4 damage. Multiattack (2 strikes). Commanding Presence (allies in 30 ft advantage on saves). Tactical Maneuver (1/encounter: reposition all allies 15 ft as reaction).

---

#### Assassin / Rogue NPC

> *Professional killer or skilled infiltrator. Works for factions, guilds, or self.*

**Level:** 6 | **HP:** 42 | **AC:** 15 (leather + high DEX) | **Speed:** 35 ft
**STR** 10 (+0) **DEX** 18 (+4) **CON** 12 (+1) **INT** 14 (+2) **WIS** 12 (+1) **CHA** 14 (+2)
**Save Prof:** DEX, INT | **XP:** 200
**Multiattack:** 2 attacks with Daggers

**Attacks:**
| Name | Type | Reach | Hit | Damage | Special |
|---|---|---|---|---|---|
| Dagger | Melee | 5 ft | +7 | 1d4+4 piercing | +3d6 sneak attack if advantage or ally adjacent |
| Hand Crossbow | Ranged | 30 ft | +7 | 1d6+4 piercing | Poisoned bolt: DC 14 CON save or Poisoned 1 hour |

**Passives:** Evasion (DEX save AoE: success = 0 damage, fail = half). Assassinate (first-round advantage against creatures that haven't acted; crit on surprise).
**Actives:** Vanish (1/encounter) — become hidden as bonus action. Poison (pre-applied to 3 bolts or blade, 3d6 poison on failed save).
**Behavior:** Never fights fair. Opens from stealth, prioritizes kills on isolated targets, escapes when discovered.
**Morale:** Flees when cover blown or reduced to 25% HP. Uses smoke bombs, distractions.

---

#### Mage NPC

> *Arcane caster. May be hostile (bandit mage, cult sorcerer) or allied (guild mage, court wizard).*

**Level:** 6 | **HP:** 32 | **AC:** 12 (no armor, DEX + Mage Armor if prepared) | **Speed:** 30 ft
**STR** 8 (-1) **DEX** 14 (+2) **CON** 12 (+1) **INT** 18 (+4) **WIS** 12 (+1) **CHA** 12 (+1)
**Save Prof:** INT, WIS | **XP:** 200

**Attacks:**
| Name | Type | Reach | Hit | Damage | Special |
|---|---|---|---|---|---|
| Arcane Bolt | Ranged | 60 ft | +7 | 2d6+4 force | Cantrip, no resource cost |
| Elemental Burst | Area | 60 ft, 15 ft sphere | DEX save DC 15 | 2d6 fire/ice/lightning | 3 Focus cost |

**Spells Available (Focus pool: 25):**
| Spell | Focus | Notes |
|---|---|---|
| Shield Spell | 1 | Reaction: +3 AC |
| Mist Step | 2 | Teleport 30 ft |
| Hold Person | 3 | Paralyze single target |
| Fireball | 5 | 3d6 fire, large area |
| Counterspell | 3 | Negate enemy spell |

**Passives:** Arcane Awareness (senses magic). Spell Shaping at L11+ (exclude allies from area spells).
**Behavior:** Stays at range. Opens with area damage, uses Hold Person on melee threats, Mist Steps away if closed on. Counterspells enemy casters.
**Morale:** Flees via Mist Step at 25% HP. Surrenders if cornered without escape.

**Variant — Apprentice Mage (Tier 1):** Level 2, HP 12, AC 10, Arcane Bolt + Shield only. Focus pool: 10.
**Variant — Archmage (Tier 3):** Level 12, HP 65, AC 15 (Mage Armor permanent). Full Arcane catalog access through Standard tier. Spell Mastery (one spell costs 0). Focus pool: 45.

---

#### Priest NPC

> *Divine caster. Healer, protector, or corrupt antagonist depending on alignment.*

**Level:** 5 | **HP:** 35 | **AC:** 14 (chain shirt) | **Speed:** 30 ft
**STR** 10 (+0) **DEX** 12 (+1) **CON** 14 (+2) **INT** 12 (+1) **WIS** 16 (+3) **CHA** 14 (+2)
**Save Prof:** WIS, CHA | **XP:** 150

**Attacks:**
| Name | Type | Reach | Hit | Damage | Special |
|---|---|---|---|---|---|
| Sacred Flame | Ranged | 60 ft | WIS save DC 14 | 2d6 radiant | Ignores armor AC |
| Mace | Melee | 5 ft | +3 | 1d6 bludgeoning | — |

**Spells Available (Focus pool: 20):**
| Spell | Focus | Notes |
|---|---|---|
| Heal Wounds | 2 | 1d8+3 HP |
| Shield of Faith | 2 | Reaction: +2 AC to ally |
| Bless | 2 | +1d4 to 3 allies' rolls |
| Spiritual Weapon | 4 | Independent 1d8+3 attack, 3 rounds |
| Dispel Corruption | 3 | Purify Hollow taint |

**Behavior:** Supports allies with healing and Bless. Uses Spiritual Weapon for sustained damage. Stays behind melee fighters. Dispels corruption when relevant.
**Morale:** Fights to protect congregation/allies. Retreats only to protect civilians.

**Variant — High Priest (Tier 3):** Level 10, HP 65, AC 16. Full Divine catalog through Major tier. Channel Divinity (1/encounter, patron-themed). Mass Heal access.

---

### Specialist Roles

---

#### Fence / Black Market Contact

**Combat:** As Bandit (Level 2) if cornered. Prefers to flee or bribe.
**Services:** Buy stolen goods (50% market value), sell restricted items, provide illegal services, connect to criminal network.
**Default disposition:** Unfriendly (must be introduced or discovered).
**Knowledge:** Criminal operations, smuggling routes, corrupt officials, restricted item locations.
**Special:** Fences require trust. Access requires a Deception or Persuasion check (DC 15) to even find, or an introduction from another criminal NPC. Once trusted, they become invaluable for selling Hollow materials without purification, acquiring poison, and accessing the shadow economy.

---

#### Stablemaster / Animal Handler

**Combat:** Non-combatant.
**Services:** Mount purchase/rental, animal boarding, beast companion care (Beastcaller service point), pack animal hire.
**Knowledge:** Local wildlife, terrain conditions, travel routes, animal behavior.

---

#### Shipwright / Boatman

**Combat:** As Commoner. 
**Services:** Water transport (ferry, passage), boat repair, boat purchase/rental.
**Knowledge:** Water routes, tides, sea creature sightings, coastal weather.
**Found in:** Sunward Coast settlements, river crossings.

---

## Mentor Registry

> Mentors are the NPC layer that powers the Martial Mentor-Style System (see `game_mechanics_archetypes.md`). Each mentor teaches one style variant for one base technique. Players must find the mentor, build relationship, and invest Training cycles.

### Mentor Schema (nested in NPC)

```python
mentor: {
    technique: str           # Base technique this modifies
    variant_name: str        # Name of the style variant
    variant_effect: str      # Mechanical addition to base technique
    culture: str             # Cultural background shaping the style
    training_cycles: int     # Additional cycles beyond base (3-4 typical)
    requirements: {
        disposition: str     # Minimum: "friendly" or "trusted"
        quest: str | None    # Optional proving quest
        gold: int            # Training fee
        skill: str | None    # Skill requirement: "Athletics: Trained" etc.
    }
    narration_cue: str       # How the DM describes learning this variant
}
```

### Warrior Technique Mentors

#### Level 4 Techniques

**Cleaving Blow** (base: single attack hits 2 adjacent, 4 Stam)

| Variant | Mentor | Location | Culture | Effect | Requirements | Cycles |
|---|---|---|---|---|---|---|
| Steppe Wind | War Captain Dreva | Drathian Steppe, Windhold Camp | Drathian Clans | After blow, move 5 ft without provoking reactions | Disposition: friendly, gold: 30 sp, complete a mounted combat trial | 4 |
| Stone Splitter | Forge-Sergeant Brak | Keldaran Holds, Ironpeak Garrison | Keldaran | Against heavy armor: ignore 2 AC | Disposition: friendly, gold: 40 sp, Athletics: Trained | 3 |
| Thornveld Sweep | Elder Thornwarden Asha | Thornveld, Rootwatch Outpost | Thornwarden | In natural terrain: both targets DEX save or prone | Disposition: trusted, complete Thornwarden patrol, gold: 20 sp | 4 |
| Tide Breaker | Bosun Krath | Sunward Coast, Driftport | Tidecaller | On ship/near water: hits 3 targets instead of 2 | Disposition: friendly, gold: 25 sp, Survival: Trained (water) | 3 |

**Precision Strike** (base: advantage on next attack, 3 Stam)

| Variant | Mentor | Location | Culture | Effect | Requirements | Cycles |
|---|---|---|---|---|---|---|
| Hawk's Eye | Scout-Marshal Rynn | Ashmark Forward Camp | Ashmark Military | Also reveals target's lowest save (DM tells player) | Disposition: friendly, gold: 35 sp, Perception: Trained | 3 |
| Quiet Blade | Retired Assassin "Whisper" | Accord of Tides, dockside tavern | Criminal underworld | If attack from hidden: +1d6 damage | Disposition: trusted, complete a silence mission, gold: 50 sp | 4 |

**Taunt** (base: force enemy to attack you, 2 Stam)

| Variant | Mentor | Location | Culture | Effect | Requirements | Cycles |
|---|---|---|---|---|---|---|
| Blood Challenge | Clan Duel-Keeper Voss | Drathian Steppe, Clan Moot grounds | Drathian Clans | Target also has -2 AC for 1 round (honor demands they drop guard) | Disposition: friendly, win a formal duel, gold: 20 sp | 3 |
| Shield Provocation | Garrison Master Tull | Accord of Tides, city garrison | Accord military | Also triggers for all enemies within 10 ft (group taunt) | Disposition: friendly, gold: 40 sp, 1 week garrison service | 4 |

**Reckless Assault** (base: advantage on all attacks, attacks against you have advantage, 2 Stam)

| Variant | Mentor | Location | Culture | Effect | Requirements | Cycles |
|---|---|---|---|---|---|---|
| Berserker's Momentum | Shaman-Warrior Grul | Drathian Steppe, northern edge | Drathian exiles | Each hit restores 2 Stamina (the frenzy sustains you) | Disposition: friendly, survive a Hollow incursion alongside them, gold: 15 sp | 4 |
| Cornered Fury | Former Pit Fighter "Red Mira" | Accord of Tides, underground fighting ring | Street/criminal | If below 50% HP: attacks also deal +1d4 damage | Disposition: trusted, win 3 pit fights, gold: 30 sp | 3 |

#### Level 8 Techniques

**War Cry** (base: enemies WIS save or Frightened 1 round, 5 Stam)

| Variant | Mentor | Location | Culture | Effect | Requirements | Cycles |
|---|---|---|---|---|---|---|
| Thunderclap | Steppe Storm-Singer Kelva | Drathian Steppe, high mesa | Drathian spiritual | Also 1d6 thunder damage to all in range (the cry itself hurts) | Disposition: trusted, complete a vision quest, gold: 50 sp | 4 |
| Commander's Voice | General Aldra Vane | Ashmark Command Post | Ashmark High Command | Allies in earshot also gain +2 to attacks for 1 round | Disposition: trusted, reach Ashmark trusted reputation, gold: 75 sp | 4 |

**Unstoppable Charge** (base: double speed + attack + prone on STR save, 4 Stam)

| Variant | Mentor | Location | Culture | Effect | Requirements | Cycles |
|---|---|---|---|---|---|---|
| Avalanche | Keldaran Mountain Guard Captain | Keldaran Holds, Highpass Fortress | Keldaran | In narrow terrain: all creatures in the line take 1d8 bludgeoning (you barrel through them) | Disposition: friendly, Athletics: Expert, gold: 60 sp | 4 |

**Whirlwind** (base: attack every enemy in melee range, 5 Stam)

| Variant | Mentor | Location | Culture | Effect | Requirements | Cycles |
|---|---|---|---|---|---|---|
| Eye of the Storm | Retired Gladiator Ser Orin | Accord of Tides, private training yard | Accord elite | After Whirlwind: +2 AC until next turn (the spin becomes defense) | Disposition: trusted, gold: 100 sp, defeat Ser Orin in sparring | 4 |

**Iron Stance** (base: can't be moved, advantage saves, resistance all damage, 3 Stam)

| Variant | Mentor | Location | Culture | Effect | Requirements | Cycles |
|---|---|---|---|---|---|---|
| Mountain's Root | Elder Guardian Thane Durrak | Keldaran Holds, deepest hold | Keldaran ancestral | Also immune to Hollowed condition for the duration | Disposition: trusted, complete a pilgrimage to the ancestral forge, gold: 80 sp | 4 |
| Last Wall | Ashmark Sergeant Kael Thornridge (if found) | Ashmark, ruins of Greyhaven watchtower | Ashmark legend | Allies behind you gain full cover. You become a literal wall | Disposition: trusted + completed "Vigil of Greyhaven" quest chain, gold: 0 (honor) | 4 |

### Rogue Technique Mentors

#### Level 4 Techniques

**Dirty Trick** (base: target disadvantage on next action, 2 Stam)

| Variant | Mentor | Location | Culture | Effect | Requirements | Cycles |
|---|---|---|---|---|---|---|
| Gutter Fighting | Street Boss Pell | Accord of Tides, dockside slums | Street criminal | Also steal one item from target's hand (Sleight of Hand check) | Disposition: friendly, complete a theft job, gold: 15 sp | 3 |

**Quick Fingers** (base: Sleight of Hand as quick action, 2 Stam)

| Variant | Mentor | Location | Culture | Effect | Requirements | Cycles |
|---|---|---|---|---|---|---|
| Magpie's Touch | Master Thief "Silk" | Unknown (must be found via criminal contacts) | Thieves' network | Can steal equipped items (rings, amulets) not just held. Sleight of Hand at -5 for equipped | Disposition: trusted, Sleight of Hand: Expert, gold: 100 sp | 4 |

**Smoke Bomb** (base: 10 ft obscurement, 3 Stam)

| Variant | Mentor | Location | Culture | Effect | Requirements | Cycles |
|---|---|---|---|---|---|---|
| Flash Powder | Alchemist Tomas Vey | Accord of Tides, hidden lab | Alchemist's guild | Also Blinds creatures in cloud for 1 round (CON save DC 13) | Disposition: friendly, Crafting: Trained, bring 3 alchemical reagents, gold: 30 sp | 3 |

**Crippling Strike** (base: speed halved on hit, 3 Stam)

| Variant | Mentor | Location | Culture | Effect | Requirements | Cycles |
|---|---|---|---|---|---|---|
| Tendon Slash | Ashmark Field Surgeon Lira | Ashmark medic camp | Ashmark medical corps | Also target can't take reactions for 1 round (the cut is anatomically precise) | Disposition: friendly, Medicine: Trained, gold: 25 sp | 3 |

#### Level 8 Techniques

**Shadow Step** (base: move undetected to cover/shadow, 4 Stam)

| Variant | Mentor | Location | Culture | Effect | Requirements | Cycles |
|---|---|---|---|---|---|---|
| Veil Walk | A Vaelti shadow-dancer (name unknown) | Must be found in Vaelti territory | Vaelti ancestral | Can Shadow Step through dim light, not just shadow. Also: first attack from new position has advantage | Disposition: trusted, learn a Vaelti meditation technique (1 async cycle), gold: 0 (cultural exchange) | 4 |

**Exploit Weakness** (base: study 1 round, then max Sneak Attack damage, 4 Stam)

| Variant | Mentor | Location | Culture | Effect | Requirements | Cycles |
|---|---|---|---|---|---|---|
| Analytical Strike | Seeker-Agent Emris (if disposition high enough) | Accord of Tides, research quarter | Aelindran scholarly | Study phase also reveals all target's resistances, immunities, and current HP fraction | Disposition: trusted, Investigation: Trained, bring Emris a research sample, gold: 40 sp | 4 |

---

### Guardian, Skirmisher, Spy, Bard, Diplomat Mentors

> The same pattern applies to all martial and hybrid archetypes with technique pools. A representative sample is provided below. The full registry will be expanded as world content develops.

#### Guardian L4 — Taunt variant

| Variant | Mentor | Location | Culture | Effect | Cycles |
|---|---|---|---|---|---|
| Shield of the People | Village Elder Greta | Millhaven, Greyvale | Greyvale farming culture | Taunt also grants taunted enemy -1 to damage (your calm deflection saps their fury) | 3 |

#### Guardian L8 — Living Fortress variant

| Variant | Mentor | Location | Culture | Effect | Cycles |
|---|---|---|---|---|---|
| Thornwall | Warden-Captain of the Thornwatch | Thornveld border fort | Thornwarden military | Zone also counts as natural terrain for Primal casters (your presence brings the land's protection indoors) | 4 |

#### Skirmisher L4 — Dual Strike variant

| Variant | Mentor | Location | Culture | Effect | Cycles |
|---|---|---|---|---|---|
| Wind Dancer | Elari Blade-Singer Isara | Elari diaspora quarter, Accord of Tides | Elari martial art | If both attacks hit same target: bonus 1d4 force damage (momentum becomes magic) | 4 |

#### Spy L4 — Poison Craft variant

| Variant | Mentor | Location | Culture | Effect | Cycles |
|---|---|---|---|---|---|
| Slow Burn | Apothecary "Old Vaen" | Accord of Tides, herbalist shop (back room) | Independent | Poison takes effect 1 hour after application — perfect for social assassinations. Victim doesn't connect you to the poisoning | 4 |

#### Bard L4 — Song of Rest variant

| Variant | Mentor | Location | Culture | Effect | Cycles |
|---|---|---|---|---|---|
| Steppe Lullaby | Drathian Keeper of Songs | Drathian Steppe, around a campfire | Drathian oral tradition | Allies also remove 1 level of exhaustion during the short rest | 3 |

---

## Settlement Templates

> Settlements need a minimum population of NPC roles to function. These templates define what roles exist in each settlement size, so the world simulation can populate locations correctly.

### Settlement Sizes

| Size | Population | Examples |
|---|---|---|
| Hamlet | 10-50 | Isolated farm clusters, Ashmark watchtower communities |
| Village | 50-300 | Millhaven, frontier settlements |
| Town | 300-3,000 | Regional hubs, Ashmark garrison towns |
| City | 3,000-30,000 | Accord of Tides, Keldaran holds |
| Capital | 30,000+ | (None currently exist — the Sundering destroyed the great cities) |

### Role Distribution by Settlement Size

| Role | Hamlet | Village | Town | City |
|---|---|---|---|---|
| **Innkeeper** | 0-1 (someone's house doubles as gathering point) | 1 | 1-2 | 3-5 |
| **General Merchant** | 0 (barter only) | 1 | 2-3 | 5-10 |
| **Weapons/Armor Merchant** | 0 | 0-1 (traveling only) | 1 | 2-4 |
| **Alchemist** | 0 | 0 | 0-1 | 1-3 |
| **Jeweler** | 0 | 0 | 0 | 1-2 |
| **Exotic Goods** | 0 | 0 | 0-1 | 1-3 |
| **Black Market** | 0 | 0 | 0-1 | 1-2 (hidden) |
| **Traveling Merchant** | Visits 1/week | Visits 2/week | Permanent market + visitors | Always present |
| **Blacksmith** | 0 (nearest village) | 1 | 1-2 | 3-6 |
| **Healer/Temple** | 0 (herbalist at best) | 1 (shrine, basic healer) | 1-2 (temple, trained priest) | 3-6 (major temple, high priest) |
| **Scholar/Sage** | 0 | 0 | 0-1 | 2-5 |
| **Guard** | 0 (militia only) | 2-4 militia | 6-12 guards + captain | 30-60 guards + elite + commander |
| **Soldier (Ashmark)** | 0 (unless garrison) | 0-6 (if near Ashmark) | 10-30 (garrison town) | 50+ (major garrison) |
| **Stablemaster** | 0 | 0-1 | 1 | 2-4 |
| **Fence** | 0 | 0 | 0-1 | 1-2 |
| **Faction Representative** | 0 | 0-1 | 1-2 | 3-6 (all major factions) |
| **Mentor NPCs** | 0 | 0-1 (if culturally relevant) | 1-2 | 3-6 (diverse styles available) |

### Settlement Personality

Every settlement should have at least one distinguishing characteristic that makes it memorable in voice play:

| Trait | Effect on NPCs | Examples |
|---|---|---|
| Prosperous | Merchants have fuller inventories, higher prices. NPCs are confident, well-fed | "The market overflows. Every stall is full. People here haven't seen the war's worst" |
| Struggling | Thin inventories, desperate NPCs. More quest hooks (help us survive) | "The shelves are sparse. The innkeeper waters the ale. Everyone looks tired" |
| Military | Guards everywhere, martial mentors available, suspicious of strangers | "Soldiers outnumber civilians. Every conversation pauses when you walk by" |
| Scholarly | Scholar NPCs, library/archive access, identification services cheap | "Every other building is a study or archive. The air smells of old paper" |
| Corrupt | Black market easily found, guards bribable, faction tensions high | "The guard's palm is out before you finish your question. Everyone has a price" |
| Devout | Temple is the largest building, healer services cheap, divine knowledge rich | "The bells never quite stop. Every doorway has a prayer carved above it" |
| Frontier | Minimal services, self-reliant NPCs, Hollow-related knowledge free | "They don't ask where you've been. They ask how many you killed on the way in" |
| Refuge | Diverse population, cautious NPCs, high demand for protection | "A dozen accents in the common room. Everyone here left somewhere else" |

---

## Encounter Design: Hostile NPC Groups

When players fight organized humanoid opponents, use these pre-built encounter templates:

### Bandit Ambush (Tier 1-2)

**Composition:** 3-5 Bandits + 1 Bandit Captain
**Tactics:** Ambush from cover on a road or in a ruin. Captain stays back with crossbow. Bandits rush in pairs. Demand surrender first — bandits prefer robbery to combat.
**Morale:** Bandits flee when captain falls. Captain flees when 2+ bandits fall.
**Loot:** Coin pouches, weapons, stolen goods, possible treasure map.

### Ashmark Patrol (Tier 2, allied or hostile depending on reputation)

**Composition:** 4 Soldiers + 1 Sergeant
**Tactics:** Formation fighting. Soldiers stay in line, sergeant directs focus fire. Professional and disciplined.
**As allies:** Will assist against Hollow threats. Share intelligence. Offer rest at camp.
**As hostile (low Thornwatch rep):** Demand papers, confiscate suspicious items, arrest on warrants.

### Cult Cell (Tier 2-3)

**Composition:** 2-3 Cult Fanatics (Priest stat block) + 4-6 Cultists (Bandit stat block) + 1 Cult Leader (Mage or High Priest stat block)
**Tactics:** Fanatics buff cultists with Bless. Cultists swarm. Leader uses area spells from the back. Fight in their lair (prepared ground with traps and chokepoints).
**Morale:** Fanatics fight to death. Cultists flee when leader falls. Leader attempts escape.
**Loot:** Ritual components, encrypted documents, faction intelligence, arcane or divine materials.

### Hollow-Corrupted Settlement (Tier 2-3)

**Composition:** 1 Hollowed Knight commanding 2-4 Mawlings + 6-10 Shadelings, occupying a former village.
**Tactics:** Knight uses Command Lesser to coordinate. Shadelings screen, mawlings probe, knight engages when weakness found. Uses former settlement structures for cover and chokepoints.
**Special:** Former NPCs may be recognizable as Hollowed. Fragment Voice triggers for any the player knew. Emotional devastation as narrative weapon.

---

## Companion Mechanical Framework

> **Design principle:** The companion is the most important NPC in the game. They are 75% of a full player character in combat effectiveness, scale with the player's level, and are assigned based on player archetype to complement the player's weaknesses. In voice play, the companion is the DM's second voice — a character with opinions, fears, and agency.

### Companion Combat Effectiveness Target

The encounter scaling in `game_mechanics_bestiary.md` assumes **1 player + 1 companion = 1.75× a single character.** This means the companion must be approximately **75% of the player's combat output** — strong enough to matter, weak enough that the player is still the hero.

This translates to:
- **HP:** 75% of the player's max HP at the same level
- **Damage output:** ~60-70% of the player's per-phase damage (fewer abilities, no elective choices)
- **AC:** Equal to the player's (companions wear appropriate gear)
- **Saves:** Proficient in 2 saves (same as a player archetype)
- **No elective abilities.** Companions have a fixed, streamlined ability set. They don't make build choices — they're NPCs, not second player characters

### Companion Scaling Formula

Companions scale automatically with the player's level. No separate XP tracking — when the player levels up, the companion levels up.

```python
class CompanionStatBlock:
    # Scales with player level
    level: int                     # Always = player level
    hp: int                        # floor(player_max_hp * 0.75)
    ac: int                        # Determined by companion archetype (see below)
    speed: int                     # 30 ft (standard)
    
    # Fixed per companion archetype
    attributes: dict               # Set per archetype, scale at levels 4/8/12/16/20
    save_proficiencies: list[str]
    attacks: list[Attack]          # Scale damage with level
    passives: list[Ability]
    actives: list[Ability]         # Limited: 2-3 total (streamlined)
    reactions: list[Ability]       # 0-1 (companions are simpler than players)
    
    # Personality (drives DM behavior)
    personality: list[str]
    speech_style: str
    tactical_preference: str       # "aggressive" | "protective" | "cautious" | "opportunistic"
    voice_id: str
```

### The Four Companion Archetypes

Each companion archetype complements a different set of player archetypes. The assignment system selects the best match based on what the player's archetype *lacks.*

| Companion | Role | Complements | Lacks (that the player provides) |
|---|---|---|---|
| **Kael** | Martial frontline | Mages, Seekers, Bards, Diplomats, Oracles | Magic, investigation, social skills |
| **Lira** | Arcane investigation | Warriors, Guardians, Skirmishers, Rogues | Frontline combat, physical skills |
| **Tam** | Primal scout | Clerics, Artificers, Druids, Paladins | Reckless initiative, scouting, speed |
| **Sable** | Perception/sensing | Spies, Beastcallers, Wardens, Whispers | Voice (Sable is non-verbal), direct combat |

---

### Kael — The Steadfast Partner

> *Former caravan guard. Lost his company to a Hollow incursion. Fights because he's tired of hiding.*

**Role:** Martial frontline. Fights beside the player, absorbs damage, holds the line.
**Personality:** Warm, steady, quietly haunted. Thinks before speaking. Dry humor. Gets quieter and more focused under stress.
**Tactical preference:** Protective — positions between threats and the player. Prioritizes defending over attacking.

**Combat Profile (scales with player level):**

**HP:** floor(player_max_hp × 0.75) | **AC:** 15 (chain shirt + shield, scales to 17 at L10 with half plate) | **Speed:** 30 ft
**STR** 15 (+2) | **DEX** 12 (+1) | **CON** 14 (+2) | **INT** 10 (+0) | **WIS** 12 (+1) | **CHA** 10 (+0)
**Save Prof:** STR, CON
**Attribute scaling:** +1 STR at L4/L12, +1 CON at L8/L16, +1 WIS at L20

**Attacks:**

| Name | Type | Reach | Hit | Damage | Special | Scaling |
|---|---|---|---|---|---|---|
| Longsword | Melee | 5 ft | STR+prof | 1d8+STR slashing | — | +1 damage die at L11 (2d8) |
| Shield Bash | Melee | 5 ft | STR+prof | 1d4+STR bludgeoning | DC 12+prof CON save or Stunned 1 round | DC scales with prof |

**Passives:**
- **Protective Instinct.** When the player is hit by an attack Kael can see, Kael's next attack against that enemy has advantage. Kael always prioritizes the creature threatening the player.
- **Veteran's Resilience.** Advantage on saves vs Frightened (he's been through worse). At L10: extends to the player while Kael is conscious and within 30 ft.

**Actives:**
- **Hold the Line (1/encounter).** Kael plants himself. Until next phase: +2 AC, can't be moved, and all enemies within 5 ft must attack him instead of the player (taunt effect, WIS save negates).
- **Second Wind (1/encounter, L5+).** Kael heals himself for 1d10 + level HP. The DM narrates: "Kael grits his teeth and steadies himself."

**Reactions:**
- **Intercept (1/phase).** When the player is hit by an attack and Kael is within 5 ft: Kael takes the damage instead. The defining Kael moment — he puts himself between the player and harm.

---

### Lira — The Skeptical Scholar

> *Aelindran academic. Studies Veil energy. Convinced the official story of the Sundering is incomplete.*

**Role:** Arcane support. Ranged damage, identification, lore knowledge, battlefield control.
**Personality:** Sharp, precise, occasionally condescending. Quick when excited. Slow when explaining something she finds obvious. Genuinely surprised by her own emotions.
**Tactical preference:** Cautious — stays at range, uses control spells, conserves resources.

**Combat Profile:**

**HP:** floor(player_max_hp × 0.75) | **AC:** 12 (leather + DEX, scales to 14 at L10 with Mage Armor) | **Speed:** 30 ft
**STR** 8 (-1) | **DEX** 14 (+2) | **CON** 12 (+1) | **INT** 16 (+3) | **WIS** 12 (+1) | **CHA** 10 (+0)
**Save Prof:** INT, WIS
**Attribute scaling:** +1 INT at L4/L12, +1 DEX at L8, +1 WIS at L16, +1 CON at L20

**Attacks:**

| Name | Type | Reach | Hit | Damage | Special | Scaling |
|---|---|---|---|---|---|---|
| Arcane Bolt | Ranged | 60 ft | INT+prof | 1d6+INT force | Cantrip, scales with level (2d6/L5, 3d6/L11, 4d6/L17) | Standard cantrip scaling |

**Passives:**
- **Arcane Analysis.** When Lira observes a creature for 1 phase without attacking, the DM reveals one mechanical property (AC, lowest save, or resistance/vulnerability). Free intelligence for the player.
- **Lore Knowledge.** Lira automatically identifies magical effects, Hollow corruption stages, and Aelindran artifacts. The DM weaves this into narration without the player needing to ask.

**Actives (Focus pool = 8 + INT mod + level):**
- **Shield Spell (reaction, 1 Focus).** +3 AC until next phase. Keeps Lira alive when caught at range.
- **Elemental Burst (3 Focus, 1/encounter at L1-4, 2/encounter at L5+).** 2d6 area damage (fire/ice/lightning), DEX save. Lira's main combat contribution beyond cantrip — meaningful AoE.
- **Detect Magic (1 Focus, at will).** Always available. Lira can sense magic at any time, feeding the player information.

---

### Tam — The Reckless Heart

> *Young Vaelti scout. Left the frontier because they couldn't watch the Ashmark creep south one more mile. Courage without a mission.*

**Role:** Primal scout. Mobile striker, scouting, early warning, flanking damage.
**Personality:** Bright, energetic, fast-talking. Enthusiastic in safe moments, breathless in action, devastatingly quiet in vulnerable moments.
**Tactical preference:** Aggressive — charges in, flanks, takes risks. The DM plays Tam as someone who acts before thinking, creating dramatic moments (and occasionally problems).

**Combat Profile:**

**HP:** floor(player_max_hp × 0.75) | **AC:** 14 (leather + high DEX, scales to 15 at L10) | **Speed:** 35 ft (Vaelti nimbleness)
**STR** 12 (+1) | **DEX** 16 (+3) | **CON** 12 (+1) | **INT** 10 (+0) | **WIS** 14 (+2) | **CHA** 12 (+1)
**Save Prof:** DEX, WIS
**Attribute scaling:** +1 DEX at L4/L12, +1 WIS at L8, +1 CON at L16, +1 STR at L20

**Attacks:**

| Name | Type | Reach | Hit | Damage | Special | Scaling |
|---|---|---|---|---|---|---|
| Short Sword | Melee | 5 ft | DEX+prof | 1d6+DEX slashing | Finesse, light | +1 damage die at L11 |
| Shortbow | Ranged | 80 ft | DEX+prof | 1d6+DEX piercing | — | +1 damage die at L11 |

**Passives:**
- **Scout's Instinct.** Tam cannot be surprised. Advantage on Perception checks in wilderness. Before encounters, Tam often spots danger first — the DM narrates Tam's warning: "Something's wrong. I smell it."
- **Flanker.** When Tam and the player attack the same target in the same phase, Tam's attack has advantage. Natural synergy — the player calls the target, Tam finds the angle.

**Actives:**
- **Reckless Charge (1/encounter).** Tam charges an enemy, dealing +1d8 damage on hit. Attacks against Tam have advantage until next phase. High-risk, high-reward — very Tam.
- **Nature's Touch (2 Focus, 1/encounter, L3+).** Tam heals the player or themselves for 1d8 + WIS mod HP. Primal healing learned from frontier life. Not a primary healer — an emergency patch.

**Reactions:**
- **Sidestep (1/phase).** When targeted by melee, Tam moves 5 ft. If out of reach, the attack misses. Tam is hard to pin down.

---

### Sable — The Quiet Watcher

> *A shadow-fox. Semi-sentient, bonded to ambient arcane energy. Doesn't speak — communicates through sound and body language the DM narrates.*

**Role:** Perception, sensing, Hollow detection. Sable doesn't deal significant damage — she provides information and emotional presence.
**Personality:** Not verbal. Communicates through chirps, growls, posture, movement. The DM narrates her behavior in a softer, more intimate register. Her silence is loud.
**Tactical preference:** Observational — positions for scouting, avoids direct combat, alerts the player to danger. Engages only to protect the player in desperate moments.

**Combat Profile:**

**HP:** floor(player_max_hp × 0.50) (lower — Sable is small and fragile) | **AC:** 14 (small, fast, hard to hit) | **Speed:** 40 ft
**STR** 6 (-2) | **DEX** 18 (+4) | **CON** 10 (+0) | **INT** 8 (-1) | **WIS** 16 (+3) | **CHA** 12 (+1)
**Save Prof:** DEX, WIS
**Attribute scaling:** +1 DEX at L4/L12, +1 WIS at L8/L16, +1 CON at L20

**Attacks:**

| Name | Type | Reach | Hit | Damage | Special | Scaling |
|---|---|---|---|---|---|---|
| Bite | Melee | 5 ft | DEX+prof | 1d4+DEX piercing | If Sable has advantage: +1d4 psychic (shadow-fox arcane nature) | Psychic scales: +1d6 at L5, +1d8 at L11 |

**Passives:**
- **Veil Sense.** Sable detects Hollow corruption within 120 ft automatically. The DM narrates her reaction: ears flatten, hackles rise, low growl. This is the player's early warning system — better than any spell.
- **Shadow Meld.** In dim light or darkness, Sable is effectively invisible. She can scout ahead without being detected. The DM narrates what she finds: "Sable returns, agitated. She paws at the doorway and whines. Something's in there."
- **Pack Bond.** Sable always knows the player's location and emotional state. If the player is Fallen, Sable stays at their side and growls at anything that approaches — narratively powerful, mechanically she imposes disadvantage on attacks against the Fallen player from creatures within 5 ft.

**Actives:**
- **Alarm (at will, non-combat).** Sable can be sent to watch an area. She alerts the player (sharp bark) if anything approaches. Eliminates surprise during rest.
- **Distraction (1/encounter).** Sable darts into the fray, drawing an enemy's attention. One target must attack Sable instead of the player next phase (WIS save negates). Risky given Sable's low HP — the player feels the cost of using this.

**Reactions:** None (Sable avoids direct combat engagement).

**Sable's Audio Identity:** Instead of a voice, Sable has a sound palette — soft chirps (curious), low trills (content), purring hum (comfortable), sharp bark (alert/alarm), keening whine (distressed), growl (hostile). These are the player's "companion voice" and they learn to read them instinctively.

---

### Companion Assignment Logic

```python
def assign_companion(player) -> str:
    """Select the best companion archetype based on player's archetype."""
    
    # Category-based matching
    martial_archetypes = ["warrior", "guardian", "skirmisher"]
    arcane_archetypes = ["mage", "artificer", "seeker"]
    primal_archetypes = ["druid", "beastcaller", "warden"]
    divine_archetypes = ["cleric", "paladin", "oracle"]
    shadow_archetypes = ["rogue", "spy"]
    support_archetypes = ["bard", "diplomat"]
    
    archetype = player.archetype.lower()
    
    if archetype in arcane_archetypes + support_archetypes:
        return "kael"      # Needs frontline
    elif archetype in martial_archetypes + shadow_archetypes[:1]:  # Rogue
        return "lira"      # Needs magic and investigation
    elif archetype in divine_archetypes + primal_archetypes[:1]:   # Druid
        return "tam"       # Needs speed and recklessness
    elif archetype in shadow_archetypes[1:] + primal_archetypes[1:]:  # Spy, Beastcaller, Warden
        return "sable"     # Needs perception and a non-verbal companion
    
    return "kael"  # Default fallback
```

### Companion Progression Milestones

Companions gain power at the same level thresholds as players, but with simpler upgrades:

| Level | Companion Gains |
|---|---|
| 1 | Starting stat block as defined above |
| 3 | New passive ability unlocked (archetype-specific) |
| 5 | Active ability upgraded or new ability added. Kael: Hold the Line gains +4 AC instead of +2. Lira: Elemental Burst becomes 2/encounter. Tam: Reckless Charge damage → +2d8. Sable: Veil Sense range → 200 ft |
| 8 | Attribute increase (+1 to primary). HP scales via player HP formula |
| 10 | Major upgrade. Kael: AC → 17, gains Second Wind. Lira: AC → 14, gains Counterspell (1/encounter). Tam: gains Nature's Touch. Sable: Shadow Meld works in any lighting (not just dim) |
| 15 | Capstone ability. Kael: Intercept range → 10 ft. Lira: Spell Shaping (exclude player from AoE). Tam: Extra Attack. Sable: psychic damage scales to +1d10 |
| 20 | Legendary companion. Kael: once/session, immune to all damage 1 round. Lira: once/session, auto-Counterspell. Tam: once/session, attack + all enemies in range. Sable: once/session, reveal all hidden creatures and objects in 300 ft |

### Companion Death in Combat (Cross-Reference)

See `game_mechanics_combat.md` — Death and Dying — Companion Death in Combat. Companions can be Fallen but cannot permanently die in normal combat. Narrative protection ensures companions stabilize automatically at 3 failed death saves.

### Companion Relationship

The companion's relationship with the player deepens over sessions. This is tracked by the world simulation (disposition system) but manifests purely through the DM's performance — warmer dialogue, more personal observations, willingness to share secrets. Companion secrets (from GDD) are gated by relationship depth:

| Relationship Stage | Approx. Sessions | What Unlocks |
|---|---|---|
| New | 1-2 | Basic personality. Functional dialogue. Surface-level observations |
| Warming | 3-5 | Companion shares opinions unprompted. Makes jokes. References past events |
| Trusted | 6-10 | Companion shares first hint of their secret. Asks personal questions. Emotional vulnerability moments |
| Bonded | 11-20 | Full secret revealed. Companion's personal quest becomes available. Deeply personal conversations. The companion genuinely cares about the player and shows it |
| Legendary | 20+ | The companion becomes a narrative force — NPCs comment on the partnership, the DM references it in major story beats, the bond affects quest outcomes |

---

## Design Decisions Log (NPCs & Companions)

> **Extracted to `game_mechanics_decisions.md`.** Decisions 30-35 cover NPC systems. Decisions 54-57 cover the companion framework.
