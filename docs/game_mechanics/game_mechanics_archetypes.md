# Divine Ruin — Game Mechanics: Archetypes & Ability Model

> **Claude Code directive:** Read `game_mechanics_core.md` first for foundational systems (attributes, skills, HP, resources, combat math). This document defines archetype profiles, the core+elective ability model, spell acquisition, and the martial mentor system.
>
> **Related docs:** `game_mechanics_core.md` (required), `game_mechanics_magic.md` (spell catalogs for caster electives), `game_mechanics_patrons.md` (divine patron modifiers)

---

## Archetype Profiles

### Chassis Components

Every archetype is defined by seven mechanical components:

1. **HP Category** — Martial (12/5), Primal-Divine (10/4), Arcane-Shadow-Support (8/3)
2. **Armor & Weapon Proficiency** — What gear can be used without disadvantage
3. **Starting Skill Proficiencies** — 3–5 skills begin at Trained
4. **Passive Abilities** — Always-on, no resource cost, checked automatically by rules engine
5. **Active Abilities** — Cost Stamina or Focus, chosen by player
6. **Reaction Abilities** — Triggered by conditions, tied to combat interrupt mechanic
7. **Archetype Milestones** — Major power thresholds at levels 5, 10, 15, 20

---

### Warrior (Martial)

> *Decisive striker, first to act, first to hit.*

**HP:** 12 base / 5 per level | **Armor:** Heavy, medium, light, shield | **Weapons:** All martial and simple
**Starting Skills (4):** Athletics, Intimidation, Perception, Survival
**Resource:** Stamina only — `8 + CON mod + level` (L1: ~10, L20: ~31)
**Recovery:** 2 Stamina/round in combat, full on short rest
**Save Proficiencies:** STR, CON
**Ability model:** All Stamina abilities are core except at L4 and L8, where the Warrior chooses from an elective technique pool. See Martial Mentor-Style System for variant training.

#### Passive Abilities

| Level | Name | Effect |
|---|---|---|
| 1 | Battle Hardened | Advantage on saving throws vs fear effects |
| 3 | Combat Momentum | After dropping an enemy to 0 HP, regain 3 Stamina |
| 9 | Brutal Critical | Critical hits roll weapon damage dice 3× instead of 2× |

#### Core Active Abilities (every Warrior)

| Level | Name | Cost | Effect |
|---|---|---|---|
| 1 | Devastating Strike | 3 Stam | +1d8 bonus damage. Scales: 2d8 at L10, 3d8 at L17 |
| 1 | Rallying Shout | 2 Stam | One ally gains advantage on next attack roll |
| 2 | Shield Bash | 2 Stam | Melee attack, stuns 1 round on hit (CON save negates) |
| 6 | Second Wind | 4 Stam | Heal self 1d10 + level HP. Once per combat |

#### Core Reactions (every Warrior)

| Level | Name | Cost | Trigger |
|---|---|---|---|
| 1 | Brace for Impact | 2 Stam | When hit: reduce damage by 1d6 + CON mod |
| 6 | Opportunity Strike | 1 Stam | When enemy moves away: free melee attack |

#### Elective Technique — Level 4 (choose 1 of 4)

Shapes mid-combat tactics. Can be swapped on long rest for an unchosen option from this pool. Each technique can be trained with NPC mentors to unlock a style variant.

| Name | Cost | Effect |
|---|---|---|
| Cleaving Blow | 4 Stam | Single melee attack hits up to 2 adjacent enemies |
| Precision Strike | 3 Stam | Gain advantage on next attack. Best against high-AC targets |
| Taunt | 2 Stam | Force one enemy to attack you for 1 round (WIS save negates). Tank/protector hybrid |
| Reckless Assault | 2 Stam | Advantage on all attacks this round, but attacks against you also have advantage |

#### Elective Technique — Level 8 (choose 1 of 4)

Defines late-game combat identity alongside L5 specialization. Same swap and mentor-variant rules.

| Name | Cost | Effect |
|---|---|---|
| War Cry | 5 Stam | All enemies in earshot: WIS save or Frightened 1 round |
| Unstoppable Charge | 4 Stam | Double speed move in straight line + attack. Target STR save or prone |
| Whirlwind | 5 Stam | Attack every enemy within melee range (one roll per target) |
| Iron Stance | 3 Stam | Until next turn: can't be moved, advantage on saves, resistance to all damage |

#### Milestones

| Level | Name | Effect |
|---|---|---|
| 5 | Specialization | **Battle Master** (tactical maneuvers: reposition, disarm, trip) or **Berserker** (rage state: +damage, costs Stamina/round) |
| 10 | Extra Attack | 2 attacks per round instead of 1 |
| 15 | Indomitable | Once per combat, reroll a failed saving throw |
| 20 | Legendary Action | Once per combat, take a full additional action on any round |

---

### Mage (Arcane)

> *Verbal spellcaster, shapes magic through spoken intent.*

**HP:** 8 base / 3 per level | **Armor:** None (unarmored only) | **Weapons:** Staff, dagger, light crossbow
**Starting Skills (4):** Arcana, History, Investigation, Nature
**Resource:** Focus only — `8 + INT mod + level` (L1: ~12, L20: ~31)
**Recovery:** None in combat (except Arcane Recovery at L15). Half on short rest, full on long rest
**Save Proficiencies:** INT, WIS
**Ability model:** Core spells are fixed and always prepared. Elective spells are learned via the Spell Acquisition System (Training, scrolls, mentors) and prepared on long rest. See Arcane Spell Catalog for the full elective pool.
**Magic source:** Arcane (Resonance rate: Focus cost × 0.6)

#### Passive Abilities

| Level | Name | Effect |
|---|---|---|
| 1 | Arcane Awareness | Sense active magical effects within earshot. DM auto-reveals magic in scenes |
| 3 | Cantrip Mastery | Cantrips cost 0 Focus and scale with level |
| 11 | Spell Shaping | Area spells can exclude up to INT mod allies from the effect |

#### Core Spells (every Mage, always prepared, don't occupy elective slots)

| Level | Name | Cost | Type | Why Core |
|---|---|---|---|---|
| 1 | Arcane Bolt | 0 (cantrip) | Cantrip | Every Mage's free baseline ranged attack |
| 1 | Shield Spell | 1 Focus | Reaction | Only defensive option. 8 HP unarmored casters need this to survive |
| 3 | Counterspell | 3 Focus | Reaction | The Mage's unique role: anti-magic specialist |
| 5 | *Specialization core* | Varies | Varies | Elementalist → Fireball (5 Focus). Arcanist → Dispel Magic (3 Focus) |
| 9 | *Specialization supreme* | 7+ Focus | Varies | Elementalist → Chain Lightning or Meteor Swarm. Arcanist → Maze or Time Stop |

#### Elective Spell Progression

Spells must be **learned** (via Training, scrolls, or mentors) before they can be **prepared** in a slot. See Spell Acquisition System.

| Level | Elective Cantrips | Elective Spell Slots | Max Tier | New at This Level |
|---|---|---|---|---|
| 1 | 1 | 1 | Minor | Choose 1 cantrip + 1 minor spell (pre-game training) |
| 2 | 1 | 2 | Minor | +1 minor slot |
| 3 | 1 | 2 | Standard | Standard tier unlocks (Counterspell is core, not elective) |
| 4 | 2 | 3 | Standard | +1 cantrip, +1 spell slot |
| 5 | 2 | 5 | Major | +2 bonus elective slots from specialization list. Major tier unlocks |
| 6 | 2 | 6 | Major | +1 slot |
| 7 | 2 | 7 | Major | +1 slot |
| 8 | 2 | 8 | Major | +1 slot |
| 9 | 2 | 8 | Supreme | Supreme tier unlocks (spec supreme is core) |
| 10 | 3 | 9 | Supreme | +1 cantrip, +1 slot. Spell Mastery: 1 elective becomes cantrip |
| 13 | 3 | 10 | Supreme | +1 slot |
| 15 | 3 | 11 | Supreme | +1 slot. Arcane Recovery milestone |
| 17 | 3 | 12 | Supreme | +1 slot. Cantrip damage scales |
| 19 | 3 | 13 | Supreme | +1 slot |
| 20 | 3 | 13 | Supreme | Reality Bend capstone. Final total: 5 core + 3 cantrips + 13 electives = 21 |

#### Milestones

| Level | Name | Effect |
|---|---|---|
| 5 | Specialization | **Elementalist** (bigger blast damage, elemental resistances, terrain effects) or **Arcanist** (utility, control, counterspelling, wider spell selection) |
| 10 | Spell Mastery | Choose one known spell costing ≤3 Focus — it becomes a cantrip (0 cost, always prepared) |
| 15 | Arcane Recovery | Once per combat, regain Focus equal to INT mod |
| 20 | Reality Bend | Once per session, change any single die result to any value you choose |

---

### Druid (Primal)

> *Speaks to the world and it answers.*

**HP:** 10 base / 4 per level | **Armor:** Medium (non-metal), light, shield (non-metal) | **Weapons:** Staff, scimitar, sling, spear
**Starting Skills (4):** Nature, Survival, Animal Handling, Perception
**Resource:** Focus-primary — Focus: `8 + WIS mod + level` (L1: ~11, L20: ~30). Stamina (secondary): `4 + CON mod` (flat, does not grow with level)
**Recovery:** Focus: half on short rest, full on long rest. Stamina: full on short rest
**Save Proficiencies:** WIS, CON
**Ability model:** Core spells are fixed. Elective spells learned via Spell Acquisition and prepared on long rest — **Druids can only change preparation in natural terrain** (must commune with the land). See Primal Spell Catalog (not yet designed).
**Magic source:** Primal (Resonance rate: Focus cost × 0.1 to 0.8, terrain-dependent)

#### Passive Abilities

| Level | Name | Effect |
|---|---|---|
| 1 | Nature's Tongue | Communicate with animals and plants. Limited — DM mediates meaning |
| 3 | Terrain Sense | In natural environments: cannot be surprised, advantage on Survival and Perception |
| 9 | Resilient Form | Advantage on saves vs poison, disease, and the Hollowed condition |

#### Core Spells (every Druid, always prepared)

| Level | Name | Cost | Type | Why Core |
|---|---|---|---|---|
| 1 | Thorn Whip | 0 (cantrip) | Cantrip | Signature ranged attack with pull — defines the Druid's combat style |
| 1 | Healing Touch | 2 Focus | Active | Druids must be able to heal. Core to the Primal source identity |
| 1 | Bark Skin | 2 Focus | Reaction | Defensive reaction. Druid survivability in medium armor |
| 5 | Wild Shape | 4 Focus + 3 Stam | Active | THE Druid identity ability. The reason people play this archetype |
| 9 | *Specialization supreme* | Varies | Varies | Land → Nature's Wrath equivalent. Beast → Improved Wild Shape capstone |

#### Elective Spell Progression

Follows same three-track model as Mage. Preparation can only change in natural terrain.

| Level | Elective Cantrips | Elective Spell Slots | Max Tier | Notes |
|---|---|---|---|---|
| 1 | 1 | 1 | Minor | Pre-game training selections |
| 2 | 1 | 2 | Minor | +1 slot |
| 3 | 1 | 2 | Standard | Standard tier unlocks |
| 4 | 1 | 3 | Standard | +1 slot |
| 5 | 1 | 5 | Major | +2 spec bonus slots. Major unlocks. Wild Shape is core |
| 7 | 1 | 7 | Major | +1 at L6, +1 at L7 |
| 9 | 1 | 7 | Supreme | Supreme unlocks (spec supreme is core) |
| 10 | 2 | 8 | Supreme | +1 cantrip, +1 slot |
| 15 | 2 | 10 | Supreme | Steady growth |
| 20 | 2 | 11 | Supreme | Final: 5 core + 2 cantrips + 11 electives = 18 total |

#### Milestones

| Level | Name | Effect |
|---|---|---|
| 5 | Specialization | **Circle of the Land** (expanded spells, terrain powers, Focus efficiency) or **Circle of the Beast** (enhanced Wild Shape, animal companion, split beast/caster) |
| 10 | Improved Wild Shape | More powerful forms. Can cast cantrips while shapeshifted |
| 15 | Nature's Wrath | Once per combat: terrain attacks all enemies in area. 4d6 damage, no save |
| 20 | Archdruid | Wild Shape costs 0 Stamina, cast all spells in beast form, beast HP regenerates 5/round |

---

### Cleric (Divine)

> *Divine conduit — god choice IS the subclass.*

**HP:** 10 base / 4 per level | **Armor:** Medium, light, shield | **Weapons:** Mace, warhammer, light crossbow
**Starting Skills (4):** Religion, Medicine, Insight, Persuasion
**Resource:** Focus-primary — Focus: `8 + WIS mod + level` (L1: ~11, L20: ~30). Stamina (secondary): `4 + CON mod` (flat)
**Recovery:** Focus: half on short rest, full on long rest. Stamina: full on short rest
**Save Proficiencies:** WIS, CHA
**Ability model:** Core spells are fixed. The L5 Domain Specialization core spell is determined by divine patron, making the Cleric the archetype most shaped by god choice. Elective spells learned via Spell Acquisition, prepared on long rest via prayer/meditation. See Divine Spell Catalog (not yet designed).
**Magic source:** Divine (Resonance rate: Focus cost × 0.3, filtered through patron)

#### Passive Abilities

| Level | Name | Effect |
|---|---|---|
| 1 | Divine Sense | Sense Hollow corruption, undead, celestial presence. Automatic reveal by DM |
| 3 | Blessed Healer | When casting healing on others, self-heal HP equal to spell's Focus cost |
| 11 | Divine Shield | While conscious, allies within earshot gain +1 to all saving throws |

#### Core Spells (every Cleric, always prepared)

| Level | Name | Cost | Type | Why Core |
|---|---|---|---|---|
| 1 | Sacred Flame | 0 (cantrip) | Cantrip | Every Cleric's free attack. WIS save (ignores armor) — divine magic bypasses physical defense |
| 1 | Heal Wounds | 2 Focus | Active | Healing is the Cleric's primary identity |
| 1 | Shield of Faith | 2 Focus | Reaction | Protecting allies is core divine function |
| 5 | *Domain core (patron-determined)* | Varies | Varies | Kaelen → Spiritual Weapon. Orenthel → Mass Heal. Syrath → Invisibility (divine shadow). Veythar → Detect Magic (enhanced) |
| 9 | *Domain supreme (patron-determined)* | 7+ Focus | Varies | Kaelen → divine battle cry. Orenthel → full party resurrection. Syrath → Veil Step. Veythar → Banishment |

#### Elective Spell Progression

Follows three-track model. Preparation changed via prayer/meditation on long rest. Patron may restrict certain spells and open others unique to their domain.

| Level | Elective Cantrips | Elective Spell Slots | Max Tier | Notes |
|---|---|---|---|---|
| 1 | 1 | 1 | Minor | Pre-game training selections |
| 2 | 1 | 2 | Minor | +1 slot |
| 3 | 1 | 2 | Standard | Standard tier unlocks |
| 4 | 1 | 3 | Standard | +1 slot |
| 5 | 1 | 5 | Major | +2 domain bonus slots. Major unlocks. Domain core is free |
| 7 | 1 | 7 | Major | +1 at L6, +1 at L7 |
| 9 | 1 | 7 | Supreme | Supreme unlocks (domain supreme is core) |
| 10 | 2 | 8 | Supreme | +1 cantrip, +1 slot. Channel Divinity milestone |
| 15 | 2 | 10 | Supreme | Greater Restoration milestone |
| 20 | 2 | 11 | Supreme | Final: 5 core + 2 cantrips + 11 electives = 18 total |

#### Milestones

| Level | Name | Effect |
|---|---|---|
| 5 | Domain Specialization | **Shaped by patron.** Kaelen: heavy armor + martial. Orenthel: enhanced healing + sanctuary. Syrath: stealth + shadow magic. Veythar: arcane knowledge + Hollow resistance |
| 10 | Channel Divinity | Powerful once-per-combat ability themed to patron god |
| 15 | Greater Restoration | Remove curses, diseases, ability drain, Hollowed condition. The only reliable Hollowed cure |
| 20 | Avatar | Once per session: channel patron deity. All abilities cost 0 Focus for 3 rounds |

---

### Rogue (Shadow)

> *Precision striker, skill specialist, master of timing.*

**HP:** 8 base / 3 per level | **Armor:** Light only | **Weapons:** Light weapons, hand crossbow, shortsword, rapier
**Starting Skills (5):** Stealth, Sleight of Hand, Investigation, Deception, Perception
*Note: 5 starting skills — most of any archetype.*
**Resource:** Stamina only — `8 + DEX mod + level` (L1: ~12, L20: ~31)
**Recovery:** 2 Stamina/round in combat, full on short rest
**Save Proficiencies:** DEX, INT
**Ability model:** All Stamina abilities are core except at L4 and L8, where the Rogue chooses from an elective technique pool. See Martial Mentor-Style System for variant training.

#### Passive Abilities

| Level | Name | Effect |
|---|---|---|
| 1 | Sneak Attack | Once/round: extra damage when attacking with advantage or ally adjacent to target. +1d6 at L1, +2d6/L5, +3d6/L9, +4d6/L13, +5d6/L17 |
| 3 | Cunning Reflexes | Cannot be surprised. Advantage on initiative rolls |
| 7 | Evasion | DEX save area effects: 0 damage on success, half on failure |

#### Core Active Abilities (every Rogue)

| Level | Name | Cost | Effect |
|---|---|---|---|
| 1 | Cunning Action | 2 Stam | Dash, disengage, or hide as quick action (in addition to main action) |
| 1 | Precise Strike | 3 Stam | Gain advantage on next attack. Enables Sneak Attack solo |

#### Core Reactions (every Rogue)

| Level | Name | Cost | Trigger |
|---|---|---|---|
| 1 | Uncanny Dodge | 2 Stam | When hit by visible attack: halve the damage |
| 5 | Slippery | 3 Stam | Restrain/grapple effect: automatically escape |

#### Elective Technique — Level 4 (choose 1 of 4)

Your approach to problem-solving beyond Sneak Attack damage. Can be swapped on long rest for an unchosen option from this pool. Mentor variants available.

| Name | Cost | Effect |
|---|---|---|
| Dirty Trick | 2 Stam | Target has disadvantage on next action. The debuffer |
| Quick Fingers | 2 Stam | Sleight of Hand as quick action (in addition to main). Steal, plant, swap mid-combat |
| Smoke Bomb | 3 Stam | 10 ft obscurement cloud. Attacks through have disadvantage. Lasts 1 round |
| Crippling Strike | 3 Stam | On hit, target speed halved until end of their next turn. The kiting build |

#### Elective Technique — Level 8 (choose 1 of 4)

Advanced technique defining late-game approach. Same swap and mentor-variant rules.

| Name | Cost | Effect |
|---|---|---|
| Shadow Step | 4 Stam | Move undetected to new position. Must end in cover/shadow |
| Exploit Weakness | 4 Stam | Study 1 round, then Sneak Attack deals max damage (no roll) |
| Vanish | 5 Stam | Become fully hidden mid-combat. Break all targeting |
| Blade Flurry | 4 Stam | 3 quick attacks at -2 each. Each can trigger Sneak Attack if conditions met |

#### Milestones

| Level | Name | Effect |
|---|---|---|
| 5 | Specialization | **Assassin** (first-strike damage, poison, disguise) or **Thief** (supreme skill mastery, item use as quick action, impossible acrobatics) |
| 10 | Reliable Talent | Any Trained+ skill: treat d20 rolls below 10 as 10 |
| 15 | Slippery Mind | Advantage on all WIS and CHA saving throws |
| 20 | Death Strike | First attack from hidden on unaware target: CON save or double total damage |

---

### Bard (Support)

> *Performer, social engine, the voice-native class.*

**HP:** 8 base / 3 per level | **Armor:** Light | **Weapons:** Light weapons, hand crossbow, longsword, rapier
**Starting Skills (5):** Persuasion, Performance, Deception, Insight, History
*Note: 5 starting skills, plus Jack of All Trades covers everything else.*
**Resource:** Split — Focus: `5 + CHA mod + floor(level/2)` (L1: ~9, L20: ~18). Stamina: `5 + CON mod + floor(level/2)` (L1: ~7, L20: ~16)
**Recovery:** Focus: half on short rest, full on long rest. Stamina: 2/round in combat, full on short rest
**Save Proficiencies:** DEX, CHA
**Ability model:** Hybrid — core spells/abilities are fixed. Elective spells chosen from **cross-source catalog** (can pick from Arcane, Divine, OR Primal catalogs). 1 elective technique at L4. See Spell Acquisition System.
**Magic source:** Bard (all three sources blended; Resonance rate: Focus cost × 0.4)

#### Passive Abilities

| Level | Name | Effect |
|---|---|---|
| 1 | Jack of All Trades | +1 to Untrained skill checks. +2 at L7, +3 at L14 |
| 3 | Bardic Knowledge | Advantage on History and Religion lore checks. DM shares extra narrative detail on success |
| 9 | Aura of Competence | All allies in earshot gain +1 to skill checks |

#### Core Spells & Abilities (every Bard, always prepared)

| Level | Name | Cost | Type | Why Core |
|---|---|---|---|---|
| 1 | Cutting Words | 0 (cantrip) | Cantrip | Signature attack + debuff. Defines the Bard's combat voice |
| 1 | Inspire | 2 Focus | Active | THE Bard ability. Giving allies dice is what Bards do |
| 1 | Dissonant Whisper | 2 Focus | Reaction | Protective reaction. Bards disrupt, not block |
| 5 | *College core* | Varies | Varies | Valor → Battle Inspiration. Lore → Cutting Words enhanced + 2 bonus Trained skills |
| 9 | Mass Inspire | 5 Focus | Active | Full-party Inspiration is the Bard's supreme support moment |

#### Core Reaction

| Level | Name | Cost | Trigger |
|---|---|---|---|
| 5 | Countercharm | 2 Focus | Ally targeted by fear/charm: give advantage on save |

#### Elective Technique — Level 4 (choose 1 of 4)

The Bard's single technique choice — how you handle yourself when words aren't enough. Mentor variants available.

| Name | Cost | Effect |
|---|---|---|
| Song of Rest | 3 Focus | During short rest: all allies regain extra 1d8 HP. The support bard |
| Cutting Retort | 2 Stam | When an enemy hits an ally, deal 1d6 psychic + target has disadvantage on next attack. The combat bard |
| Silver Tongue | 2 Focus | Outside combat: advantage on next Persuasion or Deception check. Reusable. The social bard |
| Mocking Flourish | 2 Stam | After an ally hits a target, deal 1d4 psychic and target can't take reactions. The coordination bard |

#### Elective Spell Progression

Bards are the only archetype that can choose electives from **any** source catalog (Arcane, Divine, or Primal). Spells must be learned via the three-track system. Preparation on long rest.

| Level | Elective Cantrips | Elective Spell Slots | Max Tier | Notes |
|---|---|---|---|---|
| 1 | 1 | 1 | Minor | Pre-game training selection. Can pick from any source |
| 2 | 1 | 2 | Minor | +1 slot |
| 3 | 1 | 2 | Standard | Standard tier unlocks |
| 4 | 1 | 3 | Standard | +1 slot (technique choice is separate) |
| 5 | 1 | 5 | Major | +2 college bonus slots. Major unlocks |
| 7 | 1 | 6 | Major | +1 slot |
| 9 | 1 | 6 | Major | Mass Inspire is core, not elective |
| 10 | 2 | 7 | Supreme | +1 cantrip, +1 slot. Magical Secrets: learn 2 abilities from ANY archetype list |
| 15 | 2 | 9 | Supreme | Steady growth. Superior Inspiration milestone |
| 20 | 2 | 10 | Supreme | Final: 5 core + 1 technique + 2 cantrips + 10 electives = 18 total |

> **Cross-source access:** The Bard's elective pool includes spells from all three catalogs. A Bard can learn Fireball (Arcane), Healing Touch (Primal), AND Bless (Divine). The Magical Secrets milestone at L10 goes further: learn 2 abilities from any archetype's *ability list*, not just spell catalogs — including martial techniques, Rogue abilities, etc.

#### Milestones

| Level | Name | Effect |
|---|---|---|
| 5 | College Choice | **College of Valor** (medium armor, martial weapons, combat Inspiration) or **College of Lore** (2 extra Trained skills, expanded spells, steal abilities from other archetypes) |
| 10 | Magical Secrets | Learn 2 abilities from ANY other archetype's list |
| 15 | Superior Inspiration | Start every combat with a free Inspire die |
| 20 | Master Performer | While conscious, all allies who hear you gain +2 to all d20 rolls |

---

## All Archetype Profiles — Complete (16 of 16)

> All 16 archetypes are now fully detailed below. The first 6 (Warrior through Bard) are above. The remaining 10 follow.

---

### Guardian (Martial)

> *The immovable protector. Fights by keeping others alive.*

**HP:** 12 base / 5 per level | **Armor:** Heavy, medium, light, shield | **Weapons:** All martial and simple
**Starting Skills (4):** Athletics, Perception, Insight, Intimidation
**Resource:** Stamina only — `8 + CON mod + level` (L1: ~10, L20: ~31)
**Recovery:** 2 Stamina/round in combat, full on short rest
**Save Proficiencies:** STR, CON
**Ability model:** Core Stamina abilities + 2 elective technique pools (L4 and L8). See Martial Mentor-Style System for variant training.

#### Passive Abilities

| Level | Name | Effect |
|---|---|---|
| 1 | Sentinel Stance | Allies within 5 ft gain +1 AC |
| 3 | Unwavering | Cannot be Frightened. Advantage on saves vs being moved, pushed, or knocked prone |
| 9 | Bastion | When you take damage, reduce it by your proficiency bonus (flat, stacks with other reductions) |

#### Core Active Abilities (every Guardian)

| Level | Name | Cost | Effect |
|---|---|---|---|
| 1 | Protective Strike | 2 Stam | Melee attack. On hit, target has disadvantage on attacks against anyone but you until next turn |
| 1 | Shield Wall | 3 Stam | Until next turn, you and all allies within 5 ft gain +2 AC. Requires shield |
| 2 | Stand Your Ground | 2 Stam | Plant yourself: can't be moved, +2 all saves, but can't move voluntarily. Until next turn |
| 6 | Rallying Defense | 4 Stam | All allies in earshot gain temp HP equal to CON mod + proficiency bonus until next short rest |

#### Core Reactions (every Guardian)

| Level | Name | Cost | Trigger |
|---|---|---|---|
| 1 | Intercept | 3 Stam | Ally within 5 ft hit: take the damage instead. Can apply your own damage reductions. THE Guardian reaction |
| 6 | Retaliating Shield | 2 Stam | When hit by melee attack: attacker takes 1d6 + STR mod damage. Requires shield |

#### Elective Technique — Level 4 (choose 1 of 4)

| Name | Cost | Effect |
|---|---|---|
| Taunt | 2 Stam | Force one enemy to attack you for 1 round (WIS save negates) |
| Body Block | 3 Stam | Move 10 ft and block a passage. No creature can pass your space until next turn |
| Challenging Shout | 3 Stam | All enemies within 15 ft: WIS save or must include you as target if attacking this round |
| Fortify | 3 Stam | Grant one ally within 30 ft resistance to next damage instance (half damage) |

#### Elective Technique — Level 8 (choose 1 of 4)

| Name | Cost | Effect |
|---|---|---|
| Unbreakable | 5 Stam | 2 rounds: all damage halved. Can't attack during this time. Pure survival |
| Inspiring Presence | 4 Stam | All allies in earshot +1 to attack rolls. Lasts 3 rounds |
| Avenger's Mark | 4 Stam | When ally drops to 0 HP: your next attack deals double damage |
| Living Fortress | 5 Stam | 10 ft zone: allies +2 AC + advantage saves, enemies -2 attacks. 2 rounds. Can't move |

#### Milestones

| Level | Name | Effect |
|---|---|---|
| 5 | Specialization | **Bulwark** (max personal defense: damage resistance, HP recovery, nearly unkillable) or **Warden-Commander** (party defense: larger auras, stronger buffs, Intercept range to 10 ft) |
| 10 | Shield Mastery | Shield AC +1. Intercept reduces damage by 1d8 before applying |
| 15 | Last Stand | Below 25% HP: all allies advantage on attacks 2 rounds + you gain +4 AC |
| 20 | Immortal Sentinel | Once per session: when you'd drop to 0 HP, drop to 1 HP + immune to all damage until end of next turn |

---

### Skirmisher (Martial)

> *The mobile fighter. Strikes from unexpected angles, never where you expect.*

**HP:** 12 base / 5 per level | **Armor:** Medium, light | **Weapons:** All martial and simple
**Starting Skills (4):** Athletics, Acrobatics, Perception, Survival
**Resource:** Stamina only — `8 + DEX mod + level` (L1: ~12, L20: ~33)
**Recovery:** 2 Stamina/round in combat, full on short rest
**Save Proficiencies:** DEX, STR
**Ability model:** Core Stamina abilities + 2 elective technique pools (L4 and L8). See Martial Mentor-Style System.

#### Passive Abilities

| Level | Name | Effect |
|---|---|---|
| 1 | Fleet of Foot | +10 ft movement speed. Difficult terrain doesn't slow you in combat |
| 3 | Opportunist | When an ally hits a creature you can see, your next attack against it has advantage (until end of next turn) |
| 9 | Blur of Steel | When you move 15+ ft before attacking, the attack deals +1d6 bonus damage |

#### Core Active Abilities (every Skirmisher)

| Level | Name | Cost | Effect |
|---|---|---|---|
| 1 | Hit and Run | 2 Stam | Melee attack, then move 15 ft without provoking reactions. Signature action |
| 1 | Flanking Strike | 3 Stam | If ally is adjacent to target: advantage + 1d6 damage. Positioning reward |
| 2 | Disengage | 1 Stam | Move full speed without provoking opportunity attacks |
| 6 | Momentum | 3 Stam | Until end of turn: each enemy hit grants +5 ft movement and +1 to next attack |

#### Core Reactions (every Skirmisher)

| Level | Name | Cost | Trigger |
|---|---|---|---|
| 1 | Sidestep | 2 Stam | Targeted by melee attack: move 5 ft. If out of range, attack auto-misses |
| 6 | Riposte | 3 Stam | Enemy misses melee attack: make a free melee attack against them |

#### Elective Technique — Level 4 (choose 1 of 4)

| Name | Cost | Effect |
|---|---|---|
| Hamstring | 3 Stam | On hit, target speed halved 2 rounds (CON save each turn) |
| Dual Strike | 3 Stam | Two attacks with light weapons, same or different targets |
| Throwing Mastery | 2 Stam | Throw weapon at range, no disadvantage + draw another free |
| Tumbling Assault | 3 Stam | Move through enemy spaces. Each enemy passed: free attack at -2 |

#### Elective Technique — Level 8 (choose 1 of 4)

| Name | Cost | Effect |
|---|---|---|
| Spring Attack | 4 Stam | Move, attack at any point, move again. Total up to double speed |
| Whirlwind | 5 Stam | Attack every enemy in melee range (one roll per target) |
| Predator's Pursuit | 3 Stam | Mark enemy: always know position, +1d6 damage. Until death or combat ends |
| Evasive Sprint | 4 Stam | Dash + advantage DEX saves + 4 AC until next turn |

#### Milestones

| Level | Name | Effect |
|---|---|---|
| 5 | Specialization | **Blade Dancer** (dual-wield mastery, bonus attacks, flowing movement) or **Outrider** (ranged+melee hybrid, mounted bonuses, longer range) |
| 10 | Extra Attack | 2 attacks per round instead of 1 |
| 15 | Uncatchable | Opportunity attacks against you have disadvantage. If miss, move 10 ft free |
| 20 | Perfect Strike | Once per combat: a hit becomes a critical hit automatically |

---

### Artificer (Arcane)

> *The maker of magical things. Bridges combat and the async crafting loop.*

**HP:** 8 base / 3 per level | **Armor:** Medium, light | **Weapons:** Simple + hand crossbow + tools as weapons
**Starting Skills (4):** Arcana, Crafting, Investigation, Sleight of Hand
**Resource:** Focus only — `8 + INT mod + level` (L1: ~12, L20: ~31)
**Recovery:** Half on short rest, full on long rest
**Save Proficiencies:** INT, CON
**Ability model:** 5 core spells/abilities + Arcane electives via Spell Acquisition System. See Arcane Spell Catalog in `game_mechanics_magic.md`.
**Magic source:** Arcane (Resonance rate: Focus cost × 0.6)

#### Passive Abilities

| Level | Name | Effect |
|---|---|---|
| 1 | Magical Tinkering | Imbue a tiny object with one property (light, recorded message, odor/sound, static visual). Up to INT mod objects |
| 3 | Tool Expertise | Crafting checks gain double proficiency bonus. Async crafting 25% faster (stacks with Aelora) |
| 9 | Flash of Genius | When you or ally makes check or save: add INT mod as reaction. INT mod times per long rest |

#### Core Spells & Abilities (every Artificer, always prepared)

| Level | Name | Cost | Type | Why Core |
|---|---|---|---|---|
| 1 | Arcane Bolt | 0 (cantrip) | Cantrip | Shared Arcane cantrip. Fired through a tool or device |
| 1 | Deploy Construct | 3 Focus | Active | Summon steel defender: HP = 3x level, AC 15, 1d6+INT attack. Acts on your turn. One active. THE Artificer ability |
| 1 | Infuse Item | 2 Focus | Active | Touch non-magical weapon/armor: +1 attack/damage or +1 AC until long rest. At L10: +2 |
| 5 | *Specialization core* | Varies | Varies | Alchemist: Experimental Elixir. Battlesmith: Improved Construct (Extra Attack, +INT damage) |
| 9 | *Specialization supreme* | Varies | Varies | Alchemist: Greater Elixir (supreme potions). Battlesmith: Arcane Fortress (Large construct, 5x level HP, siege) |

#### Elective Spell Progression

| Level | Elective Cantrips | Elective Spell Slots | Max Tier | Notes |
|---|---|---|---|---|
| 1 | 1 | 1 | Minor | Pre-game training |
| 3 | 1 | 2 | Standard | Standard unlocks |
| 5 | 1 | 5 | Major | +2 spec bonus. Major unlocks |
| 9 | 1 | 7 | Supreme | Supreme unlocks (spec supreme core) |
| 10 | 2 | 8 | Supreme | +1 cantrip, +1 spell |
| 15 | 2 | 10 | Supreme | Steady growth |
| 20 | 2 | 11 | Supreme | Final: 5 core + 2 cantrips + 11 electives = 18 |

#### Milestones

| Level | Name | Effect |
|---|---|---|
| 5 | Specialization | **Alchemist** (potion crafting, healing elixirs, area concoctions) or **Battlesmith** (enhanced construct, martial proficiency, INT for weapon attacks) |
| 10 | Arcane Armory | Infuse Item affects up to 3 items. Can infuse construct's attacks |
| 15 | Master Craftsman | Crafting skill treated as Master. Async crafting time halved. Can repair Masterwork items |
| 20 | Soul of Artifice | +1 to all saves per active infused item (max +4). At 0 HP: destroy infused item, regain 1d8+INT HP |

---

### Seeker (Arcane)

> *The arcane investigator. Finds what is hidden. Central to the mystery questline.*

**HP:** 8 base / 3 per level | **Armor:** Light only | **Weapons:** Simple + hand crossbow
**Starting Skills (5):** Arcana, Investigation, Perception, History, Insight
*Note: 5 starting skills — tied for most of any archetype.*
**Resource:** Focus only — `8 + INT mod + level` (L1: ~12, L20: ~31)
**Recovery:** Half on short rest, full on long rest
**Save Proficiencies:** INT, WIS
**Ability model:** 5 core spells + Arcane electives via Spell Acquisition System. See Arcane Spell Catalog.
**Magic source:** Arcane (Resonance rate: Focus cost × 0.6)

#### Passive Abilities

| Level | Name | Effect |
|---|---|---|
| 1 | Arcane Sight | Magical effects auto-identified without check. See magic like others see color |
| 3 | Analytical Mind | Investigation checks half time. Successful Investigation: DM provides one additional detail beyond what was asked |
| 11 | True Seeing | See through illusions, disguises, shapeshifting automatically. See invisible creatures. DM reveals all deceptions |

#### Core Spells (every Seeker, always prepared)

| Level | Name | Cost | Type | Why Core |
|---|---|---|---|---|
| 1 | Arcane Bolt | 0 (cantrip) | Cantrip | Enhanced: on hit, learn one mechanical property of target (AC, lowest save, HP fraction) |
| 1 | Detect Magic | 1 Focus | Active | Enhanced: also reveals Resonance levels and Veil integrity |
| 3 | Identify | 2 Focus | Active | Touch: learn all magical properties, enchantments, curses, creation history, Hollow corruption stage |
| 5 | *Specialization core* | Varies | Varies | Diviner: Scrying. Inquisitor: Enhanced Arcane Eye (interacts, passes wards) |
| 9 | *Specialization supreme* | Varies | Varies | Diviner: Foresight. Inquisitor: Legend Lore |

#### Elective Spell Progression

| Level | Elective Cantrips | Elective Spell Slots | Max Tier | Notes |
|---|---|---|---|---|
| 1 | 1 | 1 | Minor | Pre-game training |
| 3 | 1 | 2 | Standard | Standard unlocks |
| 5 | 1 | 5 | Major | +2 spec bonus. Major unlocks |
| 9 | 1 | 7 | Supreme | Supreme unlocks |
| 10 | 2 | 8 | Supreme | +1 cantrip, +1 spell |
| 15 | 2 | 10 | Supreme | Steady growth |
| 20 | 2 | 11 | Supreme | Final: 5 core + 2 cantrips + 11 electives = 18 |

#### Milestones

| Level | Name | Effect |
|---|---|---|
| 5 | Specialization | **Diviner** (foresight, scrying, probability — see the future) or **Inquisitor** (investigation, ward-breaking, secrets — analyze the present) |
| 10 | Arcane Revelation | Once per long rest: ask the DM a question about any magical phenomenon. Always true, always detailed |
| 15 | Piercing Insight | Spells ignore magical resistance/immunity. Counterspell cannot negate your spells |
| 20 | Omniscience | Once per session: DM reveals the most important hidden truth about the current situation |

---

### Beastcaller (Primal)

> *Bonds with creatures of Aethos. Your companion is your second voice.*

**HP:** 10 base / 4 per level | **Armor:** Medium (non-metal), light | **Weapons:** Simple + spear, shortbow
**Starting Skills (4):** Animal Handling, Nature, Perception, Survival
**Resource:** Focus-primary — Focus: `8 + WIS mod + level` (L1: ~11, L20: ~30). Stamina (secondary): `4 + CON mod` (flat)
**Recovery:** Focus: half on short rest, full on long rest. Stamina: full on short rest
**Save Proficiencies:** WIS, DEX
**Ability model:** 5 core spells/abilities + Primal electives. See Primal Spell Catalog in `game_mechanics_magic.md`. Lower total reflects companion investment.
**Magic source:** Primal (terrain-variable Resonance)

#### Passive Abilities

| Level | Name | Effect |
|---|---|---|
| 1 | Beast Bond | Bonded companion (chosen at creation). Share senses as action. Obeys verbal commands. If dies: revive via 8-hour ritual (1 async cycle) |
| 3 | Pack Tactics | When you and companion attack same target same round, both attacks have advantage |
| 9 | Shared Resilience | When you or companion saves, the other can use reaction to grant advantage on the save |

#### Core Spells & Abilities (every Beastcaller, always prepared)

| Level | Name | Cost | Type | Why Core |
|---|---|---|---|---|
| 1 | Thorn Whip | 0 (cantrip) | Cantrip | Pull targets toward companion for Pack Tactics |
| 1 | Command Companion | 1 Focus | Active | Direct companion: Attack (1d6+WIS), Dash, Dodge, Guard, or Scout |
| 1 | Healing Touch | 2 Focus | Active | Shared Primal healing. Can target companion |
| 5 | *Specialization core* | Varies | Varies | Pack Leader: Conjure Animals. Alpha: Dire companion (+HP, +damage, new abilities) |
| 9 | *Specialization supreme* | Varies | Varies | Pack Leader: Animal Shapes. Alpha: Legendary companion (flight/burrow, INT 8+) |

#### Elective Spell Progression

| Level | Elective Cantrips | Elective Spell Slots | Max Tier | Notes |
|---|---|---|---|---|
| 1 | 1 | 1 | Minor | Pre-game training |
| 3 | 1 | 2 | Standard | Standard unlocks |
| 5 | 1 | 4 | Major | +2 spec bonus. Major unlocks |
| 9 | 1 | 6 | Supreme | Supreme unlocks |
| 10 | 2 | 7 | Supreme | +1 cantrip, +1 spell |
| 15 | 2 | 9 | Supreme | Steady growth |
| 20 | 2 | 10 | Supreme | Final: 5 core + 2 cantrips + 10 electives = 17 |

#### Milestones

| Level | Name | Effect |
|---|---|---|
| 5 | Specialization | **Pack Leader** (multiple beasts, summoning, swarm tactics) or **Alpha** (one supreme companion evolving toward sapience) |
| 10 | Empathic Link | Full telepathy with companion. Companion +2 all saves. Cast cantrips through companion |
| 15 | Apex Bond | Companion attacks magical. When companion deals damage, you heal 2 HP |
| 20 | One Soul | Once per session: merge with companion 1 min. Combined abilities, HP pools, companion form layered over yours |

---

### Warden (Primal)

> *The primal guardian of places. Your strength is the land's strength.*

**HP:** 10 base / 4 per level | **Armor:** Heavy (non-metal), medium, light, shield | **Weapons:** Simple + martial polearms/hammers
**Starting Skills (4):** Nature, Survival, Athletics, Perception
**Resource:** Focus-primary — Focus: `8 + WIS mod + level` (L1: ~11, L20: ~30). Stamina (secondary): `6 + CON mod` (flat, higher than other Primal)
**Recovery:** Focus: half on short rest, full on long rest. Stamina: full on short rest
**Save Proficiencies:** CON, WIS
**Ability model:** 5 core abilities (mix of Focus and Stamina) + Primal electives. See Primal Spell Catalog.
**Magic source:** Primal (terrain-variable, further reduced in home territory via Rooted)

#### Passive Abilities

| Level | Name | Effect |
|---|---|---|
| 1 | Rooted | Choose home terrain at creation (forest, mountain, coast, plains, underground). In home terrain: +2 AC, advantage Survival/Perception, Resonance multiplier improves one additional step |
| 3 | Territorial Awareness | In home terrain: know location of every creature within 120 ft |
| 9 | Ancient Endurance | In home terrain: regain 1 HP start of each turn. Outside: gain after 24+ hours in any natural terrain |

#### Core Spells & Abilities (every Warden, always prepared)

| Level | Name | Cost | Type | Why Core |
|---|---|---|---|---|
| 1 | Shillelagh | 0 (cantrip) | Cantrip | Staff uses WIS, 1d8 damage. Warden melee identity |
| 1 | Guardian Strike | 2 Stam | Active | Melee attack. On hit: terrain eruption, target's next attack disadvantage |
| 1 | Bark Skin | 2 Focus | Reaction | Shared Primal defensive reaction |
| 5 | *Specialization core* | Varies | Varies | Sentinel: Nature's Bastion (Veil Ward, area control). Avenger: Primal Smite (terrain-typed melee damage) |
| 9 | *Specialization supreme* | Varies | Varies | Sentinel: Earthquake. Avenger: Guardian of Nature (permanent in home terrain) |

#### Elective Spell Progression

| Level | Elective Cantrips | Elective Spell Slots | Max Tier | Notes |
|---|---|---|---|---|
| 1 | 1 | 1 | Minor | Pre-game training |
| 3 | 1 | 2 | Standard | Standard unlocks |
| 5 | 1 | 4 | Major | +2 spec bonus. Major unlocks |
| 9 | 1 | 6 | Supreme | Supreme unlocks |
| 10 | 2 | 7 | Supreme | +1 cantrip, +1 spell |
| 15 | 2 | 9 | Supreme | Steady growth |
| 20 | 2 | 10 | Supreme | Final: 5 core + 2 cantrips + 10 electives = 17 |

#### Milestones

| Level | Name | Effect |
|---|---|---|
| 5 | Specialization | **Sentinel** (area defense, Veil Ward, terrain control) or **Avenger** (terrain-empowered melee, primal smite) |
| 10 | Terrain Mastery | Choose second home terrain. Both grant full Rooted benefits |
| 15 | Land's Fury | In home terrain: once per combat, terrain attacks all grounded enemies. 3d8 terrain-typed, no save |
| 20 | Primeval Champion | In home terrain: all primal spells 0 Resonance. HP regen 5/round. A force of nature |

---

### Paladin (Divine — Hybrid)

> *The sworn champion. Martial prowess meets divine mandate. Oath-bound.*

**HP:** 10 base / 4 per level | **Armor:** Heavy, medium, light, shield | **Weapons:** All martial and simple
**Starting Skills (4):** Athletics, Religion, Persuasion, Medicine
**Resource:** Focus-primary (hybrid) — Focus: `6 + WIS mod + level`. Stamina: `6 + CON mod + floor(level/3)`
**Recovery:** Focus: half on short rest, full on long rest. Stamina: 2/round, full on short rest
**Save Proficiencies:** WIS, CHA
**Ability model:** Hybrid — core abilities from both Stamina and Focus. 1 elective technique (L4). Limited Divine elective spells (caps at Major tier, no Supreme). See Divine Spell Catalog.
**Magic source:** Divine (Resonance rate: Focus cost × 0.3)

#### Passive Abilities

| Level | Name | Effect |
|---|---|---|
| 1 | Divine Aura | Allies within 10 ft gain +1 to saves |
| 3 | Oath-Bound | Patron-themed oath (sworn aloud at creation). Valor (Kaelen): +1 attack vs outnumbering foes. Justice (Valdris): advantage Insight vs sworn enemies. Mercy (Orenthel): healing on fallen doubles. Shadow (Syrath): advantage Stealth. **Breaking oath: lose all divine abilities until atonement** |
| 9 | Aura of Courage | Allies within 10 ft immune to Frightened while you're conscious |

#### Core Abilities (every Paladin — Stamina and Focus mix)

| Level | Name | Cost | Type | Why Core |
|---|---|---|---|---|
| 1 | Sacred Flame | 0 (cantrip) | Cantrip | Divine ranged option |
| 1 | Divine Smite | 2-6 Focus | On melee hit | Radiant damage: 2F=+1d8, 4F=+2d8, 6F=+3d8. +1d8 vs Hollow/undead. THE Paladin ability |
| 1 | Lay on Hands | Stamina pool | Active | Healing pool = 5 x level HP. Touch to heal. Or 5 pts to cure disease/poison. Resets long rest |
| 1 | Shield of Faith | 2 Focus | Reaction | Shared Divine: +2 AC to ally when attacked |
| 2 | Shield Bash | 2 Stam | Active | Shared Martial stun attack |

#### Elective Technique — Level 4 (choose 1 of 4)

| Name | Cost | Effect |
|---|---|---|
| Zealous Charge | 3 Stam | Double speed line move + melee at end. On hit: +1d6 radiant |
| Cleansing Strike | 3 Stam | On hit: remove one negative condition from yourself |
| Sanctified Ground | 3 Focus + 3 Stam | Create Veil Ward (15 ft, 3 rounds). Emergency Veil reinforcement |
| Commanding Presence | 2 Stam | All enemies within 15 ft: WIS save or can't move away 1 round |

#### Divine Elective Spell Progression (limited)

| Level | Elective Spells | Max Tier | Notes |
|---|---|---|---|
| 3 | 1 | Minor | First divine elective |
| 5 | 3 | Standard | +2 from oath specialization |
| 9 | 4 | Major | Major unlocks. **No Supreme access** |
| 15 | 5 | Major | Slow growth reflects martial focus |
| 20 | 6 | Major | Final: cores + 1 cantrip + 1 technique + 6 divine spells |

#### Milestones

| Level | Name | Effect |
|---|---|---|
| 5 | Oath Specialization | Kaelen: **Champion** (Extra Attack, martial). Valdris: **Inquisitor** (anti-evil, detection). Orenthel: **Redeemer** (enhanced Lay on Hands). Syrath: **Shadow Knight** (Stealth, shadow smite) |
| 10 | Extra Attack | 2 attacks per round. Each can trigger Divine Smite. Damage explosion |
| 15 | Cleansing Aura | Allies within 10 ft advantage on saves vs Hollowed condition |
| 20 | Divine Champion | Once per session: wings of light. 60 ft fly, +2d8 radiant on attacks, allies in 30 ft heal 10 HP per hit. 1 minute |

---

### Oracle (Divine)

> *Touched by fate. Receives visions. Bends probability. The narrative wildcard.*

**HP:** 8 base / 3 per level | **Armor:** Light only | **Weapons:** Simple only
**Starting Skills (4):** Religion, Insight, Perception, Arcana
**Resource:** Focus-primary — Focus: `8 + WIS mod + level` (L1: ~11, L20: ~30). Stamina (secondary): `4 + CON mod` (flat)
**Recovery:** Focus: half on short rest, full on long rest. Stamina: full on short rest
**Save Proficiencies:** WIS, CHA
**Ability model:** 5 core spells + Divine electives. See Divine Spell Catalog. Oracle can serve Zhael AND another patron — dual allegiance unique to this archetype.
**Magic source:** Divine (Resonance rate: Focus cost × 0.3)

#### Passive Abilities

| Level | Name | Effect |
|---|---|---|
| 1 | Prophetic Visions | Start of each session: DM gives cryptic vision fragment related to coming events. Vague at low levels, increasingly specific |
| 3 | Probability Sense | Before any d20 roll, sense whether odds are favorable, neutral, or unfavorable. DM says "feels good," "uncertain," or "the pattern resists" |
| 9 | Fate-Touched | Once per long rest: after a d20 is rolled, swap result with a roll from earlier in the session |

#### Core Spells (every Oracle, always prepared)

| Level | Name | Cost | Type | Why Core |
|---|---|---|---|---|
| 1 | Sacred Flame | 0 (cantrip) | Cantrip | Shared Divine cantrip |
| 1 | Fate's Nudge | 2 Focus | Active | After d20 roll, before narration: add or subtract 1d4 from result |
| 1 | Shield of Faith | 2 Focus | Reaction | Shared Divine reaction |
| 5 | *Specialization core* | Varies | Varies | Fateseer: Augury. Doomcaller: Hex (disadvantage on chosen ability) |
| 9 | *Specialization supreme* | Varies | Varies | Fateseer: Foresight (advantage everything 8 hours). Doomcaller: Power Word: Stun |

#### Elective Spell Progression

| Level | Elective Cantrips | Elective Spell Slots | Max Tier | Notes |
|---|---|---|---|---|
| 1 | 1 | 1 | Minor | Pre-game training |
| 3 | 1 | 2 | Standard | Standard unlocks |
| 5 | 1 | 5 | Major | +2 spec bonus. Major unlocks |
| 9 | 1 | 7 | Supreme | Supreme unlocks |
| 10 | 2 | 8 | Supreme | +1 cantrip, +1 spell |
| 15 | 2 | 10 | Supreme | Steady growth |
| 20 | 2 | 11 | Supreme | Final: 5 core + 2 cantrips + 11 electives = 18 |

#### Milestones

| Level | Name | Effect |
|---|---|---|
| 5 | Specialization | **Fateseer** (divination, foresight — support oracle) or **Doomcaller** (curses, probability as weapon — offensive oracle) |
| 10 | Temporal Echo | Once per combat: take a full second turn immediately after yours. Time stutters |
| 15 | Weave Reading | Visions become highly specific. Once per session: "I foresaw this" — advantage all rolls 1 round |
| 20 | Master of Fate | Once per session: declare a physically possible outcome. It happens. No roll. 6 Resonance |

---

### Spy (Shadow)

> *The social infiltrator. Your actual voice is your weapon.*

**HP:** 8 base / 3 per level | **Armor:** Light only | **Weapons:** Light weapons, hand crossbow, garrote
**Starting Skills (5):** Deception, Persuasion, Insight, Stealth, Performance
**Resource:** Stamina only — `8 + CHA mod + level` (Note: CHA, not DEX — social energy fuels the Spy)
**Recovery:** 2 Stamina/round in combat, full on short rest
**Save Proficiencies:** CHA, WIS
**Ability model:** Core Stamina abilities + 2 elective technique pools (L4 and L8). See Martial Mentor-Style System.

#### Passive Abilities

| Level | Name | Effect |
|---|---|---|
| 1 | False Face | Maintain one false identity at all times without checks. NPCs accept until given direct evidence |
| 3 | Read the Room | Entering social encounter: DM reveals most influential NPC and their emotional state |
| 9 | Deep Cover | Maintain up to 3 simultaneous identities. Magical truth detection must beat your Deception |

#### Core Active Abilities (every Spy)

| Level | Name | Cost | Effect |
|---|---|---|---|
| 1 | Honeyed Words | 2 Stam | Advantage on next Deception/Persuasion/Intimidation. In combat: target disadvantage next action (WIS save) |
| 1 | Backstab | 3 Stam | Attack creature that considers you ally: +2d6 + Stunned 1 round (no save — betrayal) |
| 2 | Quick Change | 2 Stam | Swap to different identity as quick action. Voice, mannerisms, apparent equipment |
| 6 | Extract Information | 4 Stam | Conversation: Deception vs Insight. Success: DM reveals one hidden thing. Fail: NPC notices probing |

#### Core Reactions (every Spy)

| Level | Name | Cost | Trigger |
|---|---|---|---|
| 1 | Plausible Deniability | 2 Stam | Accused/confronted: Deception reaction. Success: accuser doubts evidence |
| 5 | Slippery | 3 Stam | Restrained/grappled: auto-escape. Shared Shadow reaction |

#### Elective Technique — Level 4 (choose 1 of 4)

| Name | Cost | Effect |
|---|---|---|
| Poison Craft | 2 Stam | Apply poison to weapon/drink. Next hit: 2d6 poison + Poisoned (CON save) |
| Misdirection | 3 Stam | Plant false evidence/trail. Investigators follow planted lead (Deception vs Investigation) |
| Lip Reading | 1 Stam | Understand visible conversations you can't hear. Through glass, across rooms |
| Garrote | 3 Stam | From hidden: silent attack, grapples + silences. 1d6/round. STR save to escape |

#### Elective Technique — Level 8 (choose 1 of 4)

| Name | Cost | Effect |
|---|---|---|
| Double Agent | 5 Stam | In cover identity: convince NPC to switch allegiance for encounter. Contested CHA |
| Vanish in Plain Sight | 4 Stam | End combat by disappearing into crowd/environment. Requires 3+ non-hostiles or cover |
| Whisper Network | 4 Stam | In settlement: learn 2 rumors (1 true, 1 partial). Learn who's asking about you |
| Sleeper Strike | 5 Stam | Social scene: mark target (Sleight of Hand). Within 1 hour: trigger unconscious 1 min (CON save) |

#### Milestones

| Level | Name | Effect |
|---|---|---|
| 5 | Specialization | **Handler** (NPC agents, intel networks, faction infiltration — spymaster) or **Operative** (solo infiltration, combat from disguise, poison — field agent) |
| 10 | Master of Disguise | False identities immune to non-magical detection. NPCs with 1+ session cover treat you as trusted friend |
| 15 | Ghost | Once per long rest: retroactively declare you were in a past scene. DM narrates your presence. Gain info shared there |
| 20 | Puppet Master | Once per session: control one NPC's actions for encounter through social manipulation. No magic, no save — just words |

---

### Diplomat (Support — Social-Martial Hybrid)

> *The negotiator. Solves encounters with words. May never swing a sword and still be the most valuable party member.*

**HP:** 8 base / 3 per level | **Armor:** Light | **Weapons:** Simple only
**Starting Skills (5):** Persuasion, Insight, Deception, History, Performance
**Resource:** Split — Focus: `5 + CHA mod + floor(level/2)`. Stamina: `5 + CHA mod + floor(level/2)`. Note: both use CHA.
**Recovery:** Focus: half on short rest, full on long rest. Stamina: 2/round, full on short rest
**Save Proficiencies:** CHA, WIS
**Ability model:** Core social abilities + 2 technique choices + very limited social-magic electives from curated list. The least magical archetype that uses Focus.
**Magic source:** Limited social-magic (Bard-like, Resonance rate: Focus cost × 0.4)

#### Passive Abilities

| Level | Name | Effect |
|---|---|---|
| 1 | Read the Room | Entering social encounter: DM reveals most influential person, disposition toward you, one thing they want |
| 3 | Diplomatic Immunity | Initiate conversation with hostile creature that understands you: can't attack for 1 round. You speak first |
| 9 | Reputation Precedes You | NPCs in civilized areas have heard of you. Starting disposition one step higher |

#### Core Abilities (every Diplomat)

| Level | Name | Cost | Type | Effect |
|---|---|---|---|---|
| 1 | Compelling Argument | 2 Focus | Active | Advantage next Persuasion/Deception + success improves NPC disposition 1 step (permanent) |
| 1 | De-escalate | 3 Focus | Active | Target hostile: CHA vs WIS. Success: combat pauses 1 round. You speak. May end combat |
| 1 | Cutting Words | 0 (cantrip) | Cantrip | Shared with Bard. 1d4 psychic + target -1d4 next roll. Only reliable combat damage |
| 1 | Inspire | 2 Focus | Active | Shared with Bard. Grant ally a die for any roll |

#### Core Reactions

| Level | Name | Cost | Trigger |
|---|---|---|---|
| 1 | Objection | 2 Stam | NPC about to act against your wishes: Persuasion check. Success: NPC hesitates 1 round. No effect on Hollow |
| 5 | Countercharm | 2 Focus | Shared with Bard. Ally vs fear/charm: advantage on save |

#### Elective Technique — Level 4 (choose 1 of 4)

| Name | Cost | Effect |
|---|---|---|
| Mediator's Presence | 3 Focus | Two NPCs in conflict: Persuasion vs both. Success: both accept compromise. Faction rep unchanged |
| Intimidating Authority | 2 Stam | Intimidation vs all enemies in earshot. Success: -2 to attacks 1 round |
| Rumor Mill | 3 Focus | In settlement: plant rumor that spreads in 24 hours. All local NPCs hear it |
| Alliance Broker | 4 Focus | Convince NPC to ally for one encounter/task. Advantage if offering something they want |

#### Elective Technique — Level 8 (choose 1 of 4)

| Name | Cost | Effect |
|---|---|---|
| Treaty | 5 Focus | Binding agreement between two parties. CHA save to resist. Breaking: disadvantage all rolls 24 hours |
| Incite | 4 Focus | Turn crowd to specific emotion. Persuasion vs highest WIS. 10 minutes |
| Sanctuary of Words | 5 Focus | While speaking: no creature in earshot can take hostile action (WIS save each round). Must keep talking |
| Undermine | 4 Focus | Target authority figure: contested CHA. Success: subordinates doubt their judgment 1 hour |

#### Limited Social-Magic Elective Spells

| Level | Elective Spells | Max Tier | Available Pool |
|---|---|---|---|
| 3 | 1 | Minor | Charm Person, Command, Sanctuary, Detect Hollow |
| 5 | 2 | Standard | + Zone of Truth, Beacon of Hope, Hold Person |
| 9 | 3 | Major | + Commune, Dominate Person, Mass Heal |
| 15 | 4 | Major | **No Supreme access** — Diplomat peak is Major tier |

#### Milestones

| Level | Name | Effect |
|---|---|---|
| 5 | Specialization | **Ambassador** (faction diplomacy, treaties, alliance-building) or **Provocateur** (manipulation, incitement, information warfare) |
| 10 | Voice of Authority | De-escalate works on groups (up to 6). Persuasion in formal settings auto-succeeds DC ≤ 15 |
| 15 | Kingmaker | Faction rep gains doubled. Disposition improvements are 2 steps instead of 1 |
| 20 | Words That Shape the World | Once per session: deliver a speech (actually speak it). Every NPC who hears: WIS save or disposition permanently Friendly. No limit. The speech that ends a war |


---

## Core + Elective Ability Model

### Overview

Every archetype's abilities are divided into **core** (fixed, automatic, identity-defining) and **elective** (player-chosen, build-defining). This applies differently to casters and martials:

- **Casters** (Focus users): ~5 core spells + elective spells chosen from source catalogs
- **Martials** (Stamina users): ~5-6 core abilities + 2 elective technique choices from curated pools
- **Hybrids** (split resource): mix of both models per archetype

### Caster Model: Core Spells + Elective Spells

Each Focus-using archetype has **5 core spells** that every member gets automatically. These are the identity-defining abilities the DM can always assume any member of that archetype possesses. All remaining spell capacity is filled by **elective spells** chosen from the archetype's source catalog.

**Core spells per caster archetype (pattern):**

| Core Slot | When Granted | Purpose |
|---|---|---|
| Core 1 | Level 1 | Signature cantrip (free baseline attack/utility) |
| Core 2 | Level 1 | Survival tool (defensive reaction or essential utility) |
| Core 3 | Level 3 | Role-defining ability (what makes this archetype unique) |
| Core 4 | Level 5 | Specialization signature (varies by L5 fork choice) |
| Core 5 | Level 9 | Specialization capstone (supreme-tier, varies by fork) |

**Mage core spells (example):**

| Level | Core Spell | Why Core |
|---|---|---|
| 1 | Arcane Bolt (cantrip) | Every Mage's free ranged attack. DM can always assume a ranged option. |
| 1 | Shield Spell (1 Focus) | Only defensive reaction. Without it, unarmored casters die immediately. |
| 3 | Counterspell (3 Focus) | The Mage's unique role: anti-magic specialist. |
| 5 | Elementalist → Fireball / Arcanist → Dispel Magic | Specialization signature. |
| 9 | Elementalist → Chain Lightning or Meteor Swarm / Arcanist → Maze or Time Stop | Specialization supreme capstone. |

**Elective spell progression (Mage):**

| Level | Elective Cantrips | Elective Spells | Max Tier | Notes |
|---|---|---|---|---|
| 1 | 1 | 1 | Minor | Starting electives (chosen at creation, represent pre-game training) |
| 2 | 1 | 2 | Minor | +1 minor |
| 3 | 1 | 2 | Standard | Counterspell is core; Standard tier unlocks for future picks |
| 4 | 2 | 3 | Standard | +1 cantrip, +1 spell |
| 5 | 2 | 5 | Major | Spec core is free. +2 bonus electives from specialization list. Major unlocks. |
| 7 | 2 | 7 | Major | +1 at L6, +1 at L7 |
| 9 | 2 | 7 | Supreme | Spec supreme is core; Supreme tier unlocks |
| 10 | 3 | 8 | Supreme | +1 cantrip, +1 spell. Spell Mastery: 1 spell becomes cantrip. |
| 15 | 3 | 11 | Supreme | Steady +1 per 1-2 levels |
| 20 | 3 | 13 | Supreme | Final: 3 elective cantrips + 13 elective spells + 5 core = 21 total |

### Martial Model: Core Abilities + Elective Techniques

Each Stamina-using archetype has **5-6 core abilities** that every member gets automatically. At **two choice points** (L4 and L8), the martial character selects from a curated pool of **4 technique options**. These pools are archetype-specific.

**Martial technique choice structure:**

| Choice Point | Pool Size | Constraint |
|---|---|---|
| Level 4 | 4 techniques | Choose 1. Shapes mid-combat tactics. |
| Level 8 | 4 techniques | Choose 1. Defines late-game identity alongside L5 specialization. |

**Swapping:** On long rest, a martial character can swap a chosen technique for an unchosen option *from the same pool*. The L4 pick can be swapped for one of the other 3 L4 options. The L8 pick can be swapped for one of the other 3 L8 options. You cannot access L8 techniques from the L4 slot.

### Hybrid and Support Models

| Category | Core | Elective |
|---|---|---|
| **Whisper** (Shadow/Arcane hybrid) | 5 core Stamina abilities + 3 core shadow spells | 2 technique choices + ~6 elective shadow spells |
| **Paladin** (Martial/Divine hybrid) | 5 core abilities (mix of Stamina and Focus) | 1 technique choice + ~6 elective divine spells |
| **Bard** (Support, cross-source) | 4 core abilities | ~10 elective spells from cross-source catalog (Arcane, Divine, or Primal) + 2 cantrips + 1 technique |
| **Diplomat** (Support, social-martial) | 4 core social abilities | 2 technique choices + limited social-magic electives |

---

## Spell Acquisition System — Three Tracks

> **Design principle:** Leveling gives you capacity. Training gives you knowledge. Long rests give you preparation. All three must align for a spell to be usable.

### Track 1: Spell Slots (from Levels)

Granted automatically on level-up. A slot is *capacity* — an empty container that can hold one known spell of the appropriate tier or lower. A new empty slot does nothing until filled with a spell you've learned.

### Track 2: Spell Knowledge (from Training)

Earned through async Training, in-session discovery, or mentor teaching. Knowledge is your *library* — the permanent collection of spells you've mastered. You can know significantly more spells than you have slots for. Once learned, a spell stays in your library permanently.

**Study cost by tier:**

| Spell Tier | Training Cycles to Learn | Approx. Real Time (1 cycle/day) |
|---|---|---|
| Cantrip | 1 cycle | 1 day |
| Minor (1-2 Focus) | 2 cycles | 2 days |
| Standard (3-4 Focus) | 3 cycles | 3 days |
| Major (5-6 Focus) | 5 cycles | ~1 week |
| Supreme (7+ Focus) | 8 cycles | ~1.5 weeks |

**Alternative learning paths:**

| Path | How It Works | Advantage |
|---|---|---|
| **Async Training** | Dedicate downtime activity to studying a specific spell from the catalog. Most reliable path. | Guaranteed progress, player controls timing |
| **Scroll discovery** | Finding/buying a spell scroll teaches the spell immediately (scroll consumed). | Instant acquisition, valuable loot type |
| **Mentor teaching** | NPC mentor teaches during in-session narrative. Costs gold + in-game time. | No async cycles required, creates NPC relationship |
| **Observation** | Witness another caster use a spell + succeed Arcana check = 1 free Training cycle toward that spell. | Organic learning from gameplay, rewards attentive players |

**Starting knowledge:** At character creation, characters know their core spells automatically plus enough elective spells to fill starting slots (representing pre-game training). The Training-to-learn loop begins from level 2 onward.

### Track 3: Spell Preparation (on Long Rest)

On each long rest, choose which known spells fill your available slots. This is your *loadout* — the spells you have ready for the coming session.

**Preparation rules:**
- Can only prepare spells you *know* (in your library)
- Can only prepare spells of a tier you have access to
- One preparation per long rest (no swapping mid-session)
- Core spells are always prepared and don't occupy elective slots
- Primal casters can only change preparation in natural terrain (Druid lore: must commune with the land)

### Why Three Tracks Matter

| Player Behavior | Result |
|---|---|
| Focuses Training on spells | Huge library, fewer skill advancements, chooses different loadouts per session |
| Focuses Training on skills | Smaller library, broader non-combat capability, consistent loadout |
| Focuses Training on attributes | Higher modifiers, thinner library, fewer Expert/Master skills |
| Discovers scrolls and mentors in-session | Expands library without spending Training cycles, more async time for other priorities |

```python
# Implementation: spell preparation check
def can_prepare_spell(character, spell) -> bool:
    return (
        spell.name in character.known_spells          # Must know it
        and spell.tier <= character.max_spell_tier     # Must have tier access
        and len(character.prepared_spells) < character.spell_slots  # Must have empty slot
    )
```

---

## Martial Mentor-Style System

> **Design principle:** Casters get breadth (many spells, large library). Martials get depth (fewer techniques, but each one can be *specialized* through mentor training into unique style variants).

### How It Works

Every martial elective technique has a **base version** — learnable through standard async Training. It takes longer than spell learning: **5-6 Training cycles** for a technique (physical mastery is harder than academic study).

If you train that technique **with a specific NPC mentor**, you learn a **style variant** — a modified version with an additional property reflecting the mentor's background, culture, and fighting philosophy.

### Base vs. Variant

| Property | Base Technique | Style Variant |
|---|---|---|
| How learned | Solo Training (5-6 cycles) | Train with mentor (base + 3-4 additional cycles) |
| Total investment | 5-6 cycles | 8-10 cycles |
| Mechanical effect | Standard ability as defined in technique pool | Standard ability + a signature twist |
| Prerequisites | Have the technique slot (L4 or L8) | Base technique known + find mentor + build relationship + complete training |
| Power level | Complete and functional | Situationally stronger (not strictly better — different) |

### Example: Cleaving Blow Variants (Warrior L4 Technique)

**Base — Cleaving Blow:** Single melee attack hits 2 adjacent enemies. 4 Stamina.

| Variant Name | Mentor Culture | Added Effect |
|---|---|---|
| *Steppe Wind* | Drathian Clans | After the blow, move 5 ft without provoking reactions. Nomad fighting style: never stop moving. |
| *Stone Splitter* | Keldaran Holds | Against targets in heavy armor, ignore 2 AC. Mountain-dwellers adapted to armored foes. |
| *Thornveld Sweep* | Thornwardens | In natural terrain, both targets must DEX save or fall prone. Forest fighters use the land. |
| *Tide Breaker* | Tidecallers | On a ship or near water, attack hits up to 3 targets (instead of 2). Sea-fighters swing wide. |

### Mentor System Integration

Mentors are NPC entities in the world data with defined properties:

```python
class TechniquesMentor:
    npc_id: str                    # Links to NPC entity
    location: str                  # Where they can be found
    culture: str                   # Cultural background
    technique: str                 # Which base technique they modify
    variant_name: str              # The style variant name
    variant_effect: str            # Mechanical modification
    requirements: dict             # Disposition threshold, quest completion, gold cost, etc.
    training_cycles: int           # Additional cycles beyond base (typically 3-4)
    narration_cue: str             # How the DM describes the training and the variant
```

**Finding mentors creates content:** The mentor's location, disposition requirements, and potential quest prerequisites mean that training a variant is 2-3 sessions of organic gameplay — travel, relationship-building, proving yourself. This emerges naturally from the martial Training system.

**Community knowledge:** Players who discover exceptional mentors in obscure locations have found something worth sharing. "There's a retired Paladin of Valdris in the Dawnspire Highlands who teaches a variant of Iron Stance that grants immunity to the Hollowed condition for 1 round" is the kind of player knowledge that builds community.

### Character Sheet Display

Mentor-variant techniques display their attribution:

> **Cleaving Blow** — *Steppe Wind variant*
> 4 Stamina · Single attack hits 2 adjacent enemies + 5 ft reposition
> *Trained under War Captain Dreva, Drathian Steppe*

The attribution line is the martial equivalent of a named weapon — players take pride in where they learned their fighting style.

### Variant Design Principles

- Variants are **situationally stronger, not universally better.** Steppe Wind is great for mobile fights, useless when cornered. Stone Splitter is great against armored enemies, irrelevant against unarmored.
- Variants are **culturally grounded.** Every variant tells a story about where it comes from.
- Variants are **optional.** The base technique is complete and competitive. Variants reward investment, not punish the lack of it.
- Multiple variants can exist per technique. A player can only learn one variant per technique (you learn one fighting style for each move, not three). Swapping variants requires finding a new mentor and investing the cycles again.

---

