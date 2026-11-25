# Divine Ruin — Game Mechanics: Divine Patron System

> **Claude Code directive:** Read `game_mechanics_core.md` first for foundational systems. This document defines all 10 divine patrons, the Unbound path, the four-layer patron system, and divine favor mechanics.
>
> **Related docs:** `game_mechanics_core.md` (required), `game_mechanics_magic.md` (Resonance modifiers per patron), `game_mechanics_archetypes.md` (archetype synergy details)

---

## Divine Patron System

### Architecture

Each divine patron provides four mechanical layers. Any archetype can follow any god, but certain combinations have enhanced effects (Layer 4). Choosing no patron (the Unbound path) is mechanically viable with its own four-layer equivalent.

**Layer 1 — Divine Gift:** A universal passive ability every follower gets regardless of archetype. The god's fingerprint on your character from level 1.

**Layer 2 — Resonance Modifier:** How this god's patronage interacts with the Resonance system. Each god has a unique relationship with the Veil.

**Layer 3 — Divine Favor Abilities:** Unlocked by divine favor milestones (alignment-based, not level-based). Three tiers: Acknowledged, Devoted, Exalted. Grow through roleplaying in accordance with the god's values, evaluated by the god-agent heartbeat.

**Layer 4 — Archetype Resonance:** 2–3 archetype categories where the god's gift takes enhanced form (natural synergy, divine synergy, unexpected synergy). Other archetypes still receive Layers 1–3 normally.

### Divine Favor Tiers

Divine favor is tracked per-player by the god-agent heartbeat (simulation layer 3, every 15–30 minutes). It fluctuates based on player behavior alignment with patron values.

**Deed journal:** A persisted per-kind pending/awarded journal keeps directly awarded actions from paying twice.
Present players are judged every 20 minutes against current persisted patrons; journals are consumed, and decay runs only at hydration.

| Tier | Threshold | How Earned | How Lost |
|---|---|---|---|
| **Acknowledged** | Low favor (default after choosing patron) | Basic alignment with god's values | Sustained contrary behavior |
| **Devoted** | Mid favor | Consistent roleplay aligned with god's values over multiple sessions | Significant betrayal of values |
| **Exalted** | High favor | Exceptional devotion, critical moments of alignment | Major violation of patron's principles |

Favor can rise and fall. A player who reaches Exalted and then acts against their god's values can drop back to Devoted or even Acknowledged. This creates meaningful roleplay tension — the abilities are earned through behavior, not grinding.

---

### Veythar, the Lorekeeper

**Domain:** Knowledge, arcane arts, discovery, memory

**Layer 1 — Divine Gift: Lorekeeper's Insight**
Once per short rest, when you fail an Arcana, History, Investigation, Nature, or Religion check, you may reroll it. You must take the new result.

**Layer 2 — Resonance Modifier: Arcane Amplification**
Arcane casters under Veythar: Flickering threshold bonus damage increases to **+2 dice** (instead of +1). The Lorekeeper understood the Wellspring better than anyone — followers tap deeper. Overreach threshold stays at 9. More reward, same risk.

> **Post-reveal:** Divine filter degrades from 0.3× to 0.7× Resonance rate. Arcane amplification remains unchanged (it was latent Wellspring knowledge, not coming from the god). Veythar's Clerics find divine casting nearly as dangerous as arcane. Crisis of faith becomes mechanically urgent.

**Layer 3 — Divine Favor Abilities**

| Tier | Name | Effect |
|---|---|---|
| Acknowledged | Scholar's Ward | Advantage on saves against the Hollowed condition |
| Devoted | Lorekeeper's Library | Once per long rest, ask the DM one mechanical question about an enemy, item, or location (AC, weakness, trap DC, etc.). The god whispers the answer |
| Exalted | Wellspring Echo | Arm once per session. The next completed Focus-costing spell costs no Focus and generates double its normal Resonance. |

Activate Wellspring Echo in or out of combat. Free and refused casts leave it armed.
Double the spell's generation after its usual modifiers, before applying decay or checking Overreach.
The arm survives reconnecting to the same session and clears when a new session begins.

**Layer 4 — Archetype Resonance**

| Archetypes | Synergy Type | Enhancement |
|---|---|---|
| Mage, Artificer, Seeker | Natural | Your arcane cantrips gain Veythar's +2 Flickering bonus damage dice even when you are not Flickering. This replaces, rather than stacks with, the Layer 2 Flickering bonus. |
| Cleric | Divine | Arcana as bonus starting skill. Divine magic auto-identifies magical effects (no check) |
| Rogue, Spy, Seeker | Unexpected | Investigation checks for hidden information gain +1. The Lorekeeper rewards seekers |

---

### Kaelen, the Ironhand

**Domain:** War, conflict, valor, martial discipline, strategy

**Layer 1 — Divine Gift: Iron Resolve**
When you drop below 25% HP for the first time in an encounter, gain +2 to attack rolls and saving throws until end of next turn.

**Layer 2 — Resonance Modifier: Martial Focus**
Resonance generated by abilities that directly aid combat (buffs, damage) reduced by 1 (minimum 0). Non-combat spells unaffected. The god of war channels power efficiently.

**Layer 3 — Divine Favor Abilities**

| Tier | Name | Effect |
|---|---|---|
| Acknowledged | Warrior's Endurance | +5 max HP permanently |
| Devoted | Battle Cry of the Ironhand | Once per long rest, all allies in earshot gain +1d4 to attack rolls for 2 rounds |
| Exalted | Kaelen's Judgment | Once per session, declare a Worthy Foe. All attacks against target gain advantage for encounter. Defeating them restores half max Stamina |

**Layer 4 — Archetype Resonance**

| Archetypes | Synergy Type | Enhancement |
|---|---|---|
| Warrior, Guardian, Skirmisher | Natural | Iron Resolve triggers at 40% HP. Extra Attack (L10) grants +1d4 permanent weapon damage |
| Paladin | Divine | Oath of Valor: sworn strikes deal +1d6 radiant vs foes that outnumber the party |
| Bard | Unexpected | War songs: Inspire dice for attack rolls upgraded one die size (d6→d8, etc.) |

---

### Aelora, the Hearthkeeper

**Domain:** Civilization, commerce, crafting, community

**Layer 1 — Divine Gift: Hearthkeeper's Bond**
+1 to all skill checks when you can see or hear an ally. Power grows from connection.

**Layer 2 — Resonance Modifier: Shared Burden**
When a Veil Ward is active in your area, your spells inside it suffer no damage/DC penalty (others still do). Aelora's civilizing influence harmonizes with Veil reinforcement.

**Layer 3 — Divine Favor Abilities**

| Tier | Name | Effect |
|---|---|---|
| Acknowledged | Craft Blessing | Async crafting 25% faster. Crafted items have chance of bonus property |
| Devoted | Community Shield | Once per long rest, immediately grant another standing, present party player temporary HP equal to your level plus your Charisma modifier (minimum 1). A smaller pool is replaced. An equal or larger pool leaves the gift unspent. Works in and out of combat with no action, reaction or distance cost. A partially resolved round or live Fate offer blocks activation. |
| Exalted | Hearthfire | Once per session, create sanctuary zone: 3 rounds, allies regain 1d6 HP/round, advantage on saves, enemies WIS save to enter |

**Layer 4 — Archetype Resonance**

| Archetypes | Synergy Type | Enhancement |
|---|---|---|
| Artificer, Bard, Diplomat | Natural | Bond bonus +2 near 2+ allies. Crafting Focus costs -1 (min 1) |
| Guardian, Warden | Divine | Protective reactions restore 2 Stamina |
| Rogue | Unexpected | Commerce Persuasion +1. Better fence prices. Aelora respects the hustle |

---

### Thyra, the Wildmother

**Domain:** Nature, seasons, growth, ecosystems, weather

**Layer 1 — Divine Gift: Nature's Pulse**
In natural terrain: advantage on Perception and Survival. Sense ecosystem health automatically (DM narrates without check).

**Layer 2 — Resonance Modifier: Veil Grounding**
In natural terrain: primal Resonance multiplier improves by one step (0.3→0.2, etc.). All casters under Thyra gain -1 Resonance per spell on natural ground. The Wildmother's land absorbs disturbance.

**Layer 3 — Divine Favor Abilities**

| Tier | Name | Effect |
|---|---|---|
| Acknowledged | Seasonal Attunement | Passive bonuses by in-game season. Spring: +1 healing received. Summer: +1 fire/lightning damage. Autumn: +1 Insight. Winter: +1 Stealth |
| Devoted | Thornwall | Once per long rest in combat, choose two points up to 30 feet apart. The nearest point of the wall must be within 30 feet of the follower, and the wall must be clear of creatures. It blocks movement and melee reach for everyone. An enemy stopped by its own move or melee approach takes 1d6 piercing damage once per turn. Ranged attacks and spells pass through. The wall has AC 19 and 20 HP. It lasts until destroyed or combat ends. |
| Exalted | Wildmother's Wrath | Once per session, activate immediately in combat on natural ground. One shared 3d8 damages every living, unprotected foe. No save. |

Wildmother's Wrath deals piercing in ancient forest and forest, slashing in grassland and farmland, bludgeoning on mountains and underground, cold on the coast, and poison in wetlands. Villages and cities refuse the gift.
The Still and its unrevealed anchors, and the Choir's unexposed core, are spared. If no living foe can be hit, the gift stays unspent.

**Layer 4 — Archetype Resonance**

| Archetypes | Synergy Type | Enhancement |
|---|---|---|
| Druid, Beastcaller, Warden | Natural | Nature's Pulse extends to non-natural terrain: +2 to Perception and Survival checks. Wild Shape +5 temp HP |
| Warrior, Skirmisher | Unexpected | Crit strikes deal +1d4 natural-type damage (thorns, stone, lightning) |
| Cleric | Divine | Healing in natural terrain +1d4 extra HP |

---

### Syrath, the Veilwatcher

**Domain:** Shadows, secrets, espionage, hidden knowledge

**Layer 1 — Divine Gift: Shadow Veil**
Once per short rest, become invisible for 1 round. Breaks on attack or spellcasting.

**Layer 2 — Resonance Modifier: Hidden Casting**
Spells cast while hidden or from stealth generate **-2 Resonance** (minimum 0). Casting from shadow barely disturbs the Veil — you're already half-between realities.

**Layer 3 — Divine Favor Abilities**

| Tier | Name | Effect |
|---|---|---|
| Acknowledged | Whisper Network | Once per long rest, learn one secret about a visible NPC (hidden motivation, lie, or vulnerability) |
| Devoted | Veilstep | Once per long rest, step to a visible shadow up to 60 feet away. Keep your full movement. Any queued move is removed. Costs 0 Resonance. |
| Exalted | The Veilwatcher's Eye | Once per session, see through the Veil for 6 seconds. DM describes what lies beyond at your current location. The most dangerous and most valuable information ability in the game |

**Layer 4 — Archetype Resonance**

| Archetypes | Synergy Type | Enhancement |
|---|---|---|
| Rogue | Natural | Shadow Veil extends to 2 rounds. Invisible Sneak Attack +1d6 |
| Spy, Whisper | Natural | Shadow Veil extends to 2 rounds. Weapon attacks from Shadow Veil deal +1d6 |
| Mage, Seeker | Unexpected | Hidden Casting reduction increases to -3. Lowest-Resonance arcane caster possible |
| Oracle | Divine | Veil-sight visions are clearer and more detailed |

---

### Orenthel, the Dawnbringer

**Domain:** Light, healing, renewal, hope, restoration

**Layer 1 — Divine Gift: Dawn's Resilience**
When you heal another creature (any source), you regain 2 HP. The light flows both ways.

**Layer 2 — Resonance Modifier: Purifying Light**
Healing spells generate **0 Resonance** regardless of source type. Restoration mends the Veil. Safest healers in the game.

**Layer 3 — Divine Favor Abilities**

| Tier | Name | Effect |
|---|---|---|
| Acknowledged | Beacon | Faint light in darkness. Hollow creatures have disadvantage on first attack against you each encounter |
| Devoted | Restoration Surge | Once per long rest, remove one negative condition (Poisoned, Blinded, Frightened, stage 1 Hollowed) by touch. No Focus cost |
| Exalted | Dawn's Embrace | Once per session, when damage drops another party player or the companion from above 0 HP to 0, they stand at half max HP, rounded down with a minimum of 1. Death Ward takes priority. A living, present follower can give while fallen. No action, range or line of sight is required. |

**Layer 4 — Archetype Resonance**

| Archetypes | Synergy Type | Enhancement |
|---|---|---|
| Cleric, Paladin | Natural | All healing spells +WIS or +CHA mod extra HP. Most powerful healing in the game |
| Druid, Beastcaller | Unexpected | Healing Touch also removes 1 Resonance from target. Active party Resonance management |
| Bard | Divine | Song of Rest +1d6 HP. Inspire dice can heal instead of buffing rolls |

---

### Valdris, the Scalebearer

**Domain:** Justice, law, truth, accountability

**Layer 1 — Divine Gift: Weight of Truth**
Once per short rest, when you speak a statement you believe to be true, compel an NPC to acknowledge it. They don't have to agree or act — but they cannot dismiss or ignore it.

**Layer 2 — Resonance Modifier: Ordered Magic**
When casting a spell targeting a specific creature that has wronged you or allies (attacked first, broken promise, committed injustice), Resonance is halved. Justice magic is orderly — the Veil recognizes righteous purpose.

**Layer 3 — Divine Favor Abilities**

| Tier | Name | Effect |
|---|---|---|
| Acknowledged | Discern Lies | Once per long rest, know with certainty whether an NPC's last statement was true, false, or deliberately misleading. No check, no save |
| Devoted | Mark of Justice | Once per long rest, mark an unjust creature for the rest of the encounter. It takes -2 on saves against your spells and abilities. |
| Exalted | The Scale's Verdict | Once per session during combat, judge one living hostile creature. The engine rules it unjust if it attacked a party member or companion in this fight, even if it missed. An unjust foe takes 4d8 radiant damage and is Stunned for one round if still standing. On a just verdict, you take 2d8 radiant damage. Valdris voices the engine's verdict. |

**Layer 4 — Archetype Resonance**

| Archetypes | Synergy Type | Enhancement |
|---|---|---|
| Paladin | Natural | Oath of Justice: oath-breaking loses all favor abilities for a session. Oath-keeping grants +2 to all d20 rolls when justice is at stake |
| Cleric, Oracle | Divine | Turn Undead/Hollow DC +1. Absolute authority against unnatural things |
| Rogue, Spy | Unexpected | Deception for just causes (evidence, infiltration) gains +1. Valdris blesses deception in service of truth |

---

### Mortaen, the Threshold

**Domain:** Death, the afterlife, transition, the boundary between life and what follows

**Layer 1 — Divine Gift: Death's Awareness**
Sense wounded creatures and party members in your location at or below 25% HP. The DM uses Death's Awareness from query_info patron to reveal their names without a check. The DM narrates signs of violent death in the area within the last day.

**Layer 2 — Resonance Modifier: Threshold Magic**
Spells cast on creatures at 0 HP (healing fallen allies, finishing dying enemies) generate **0 Resonance**. Magic touching the life-death boundary flows through Mortaen's domain naturally.

**Layer 3 — Divine Favor Abilities**

| Tier | Name | Effect |
|---|---|---|
| Acknowledged | Death Ward | When damage would reduce you from above 0 HP to 0 HP, you automatically stay at 1 HP before instant death or a Hollowed rise is resolved. Recharges on a long rest. Mortaen decides when you cross. |
| Devoted | Speak with Dead | Once per long rest, commune with a deceased creature's spirit. 3 questions, truthful but terse answers |
| Exalted | Threshold Walk | Once per session, become incorporeal through the end of the next round. Slashing, piercing and bludgeoning pass through you, even when magical. Attacks against you have disadvantage, your attacks have advantage, and your weapon attacks deal necrotic damage. You cannot drop below 1 HP. You return Shaken unless combat ends first. |

**Layer 4 — Archetype Resonance**

| Archetypes | Synergy Type | Enhancement |
|---|---|---|
| Cleric | Natural | Sacred Flame deals necrotic. Healing on 0 HP allies restores double. Best at pulling people back from the edge |
| Rogue, Whisper | Unexpected | Death's Touch: Sneak Attack that drops target to 0 HP makes no sound or mark. The perfect silent kill |
| Druid, Warden | Divine | When a creature dies within earshot, regain 2 Focus. Death feeds renewal |

---

### Nythera, the Tidecaller

**Domain:** Sea, travel, exploration, boundaries, the unknown

**Layer 1 — Divine Gift: Horizon Sense**
The DM narrates north. Horizon Sense from query_info patron reveals travel hours since your last long rest and the nearest location you have never visited, measured in exit legs. Advantage on Survival in unknown territory.

**Layer 2 — Resonance Modifier: Boundary Walker**
Spells cast in locations you've never visited before generate **-1 Resonance** (minimum 0). The frontier Veil is more flexible — it hasn't been stressed by prior casting.

**Layer 3 — Divine Favor Abilities**

| Tier | Name | Effect |
|---|---|---|
| Acknowledged | Tidewalker | Ignore water/mud/shifting ground difficult terrain. Full speed through slowing environments |
| Devoted | Charted Course | Once per long rest, learn the safest route between two known locations (fewest encounters, lowest Hollow exposure) |
| Exalted | Beyond the Horizon | Once per session outside combat, bring the whole party through a gateway to another location the follower has visited. The follower gains exactly 5 Resonance. The Still can prevent departure. |

When ready, `query_info(kind="patron")` lists visited destinations for Beyond the Horizon. Pass one of those location IDs as `target_id` to `activate`. The gateway refuses unknown, unvisited, and current locations. A successful crossing advances any quest stage reached by arriving there.

**Layer 4 — Archetype Resonance**

| Archetypes | Synergy Type | Enhancement |
|---|---|---|
| Seeker, Spy | Natural | Investigation and Perception +3 in unexplored locations |
| Skirmisher, Rogue | Unexpected | Once per encounter, reposition to any visible unoccupied space without provoking reactions |
| Druid, Beastcaller | Divine | Wild creatures in new territory predisposed friendly. Animal Handling +1 in unexplored areas |

---

### Zhael, the Fatespinner

**Domain:** Fate, time, prophecy, luck, the pattern of things

**Layer 1 — Divine Gift: Fate's Thread**
Once per long rest, after seeing a d20 result (yours or anyone's), force a reroll. Either result can be chosen.

**Layer 2 — Resonance Modifier: Pattern Weaving**
Unique interaction: instead of modifying generation rates, Zhael alters the Hollow Echo table. At Resonance 9+, Zhael followers roll **2d20 on the Echo table and choose which result to keep**. Fate doesn't prevent Overreach — it lets you navigate it.

**Layer 3 — Divine Favor Abilities**

| Tier | Name | Effect |
|---|---|---|
| Acknowledged | Lucky | Once per long rest, turn a natural 1 into a natural 20, or a natural 20 into a natural 1 (before result is narrated) |
| Devoted | Prophecy Fragment | Start of each session, DM gives a cryptic one-sentence prophecy. Recognizing the moment and acting on it grants advantage |
| Exalted | Unravel Fate | Once per session, undo one event from the last round. Damage reversed, positions restored, resources returned. One round unhappens. Generates 8 Resonance on the user regardless of caster status |

**Layer 4 — Archetype Resonance**

| Archetypes | Synergy Type | Enhancement |
|---|---|---|
| Oracle | Primary | Prophecy Fragment becomes 2-sentence vision with more detail. Fate's Thread usable twice per long rest |
| Bard, Diplomat | Unexpected | Social encounters: once per encounter, know the exact DC of the next social check before attempting |
| Rogue, Mage | Divine | Critical hits on natural 19–20 (expanded crit range). Zhael bends probability |

---

### The Unbound Path (No Patron)

> **Design intent:** The Unbound path is mechanically viable, not a trap. It trades divine safety nets and favor abilities for unmediated Veil awareness, voluntary risk control, and unique endgame relevance.

**Cosmological rationale:** The Unbound don't channel through a god. Their magic is entirely self-sourced. In the post-Sundering world, this means no divine filter — but also no divine lens coloring their perception. They see the Veil *raw*.

**Layer 1 — Unbound Gift: Veil Clarity**
You can sense your **own exact Resonance value** as a number (DM shares on request). No other character gets this — even Elari sense states, not numbers. This enables perfectly informed risk decisions.

**Layer 2 — Resonance Modifier: Raw Channeling**
Standard Resonance generation (no divine reduction). But once per encounter, you can **voluntarily raise your Resonance by 3** — pushing yourself into Flickering or Overreach deliberately. Patron characters reach high Resonance through accumulation; the Unbound *choose* it. Raw Channeling consumes neither an action nor a reaction.

**Layer 3 — Self-Reliance Milestones** (replace divine favor, tracked by autonomy instead of patron alignment)

Autonomy persists on the player, starting at 0 with a default maximum of 100. The existing 20-minute deed judgment awards each deed kind once per judgment window:

| Deed | Autonomy | Qualification |
|---|---|---|
| `won_alone` | +4 | Victory with enemies cleared and no ally present for the actor |
| `succeeded_alone` | +1 | A successful check without an ally |
| `channeled_raw` | +2 | Use Raw Channeling |

Self-Reliant starts at 0, Self-Forged at 40% and Sovereign at 75% of the track's maximum. Fractional thresholds round upward. Autonomy never decays and attained tiers never regress.

| Tier | Name | Effect |
|---|---|---|
| Self-Reliant | Additional Save Proficiency | Gain proficiency in one additional saving throw of your choice; a durable, one-time choice |
| Self-Forged | Divine Immunity | Once per long rest, choose to be unaffected by any divine ability (ally boon, enemy smite, god-agent intervention). You exist outside the gods' direct influence |
| Sovereign | Veil Mastery | At Sovereign, automatically convert the first Hollow Echo of each session to "Nothing stirs." Later Echoes apply normally |

A naturally harmless first Echo also consumes Veil Mastery. Rest does not restore it; a fresh session does. Divine Immunity recharges on a long rest.

Human decision 2026-11-18, sprint `unbound-self-reliance`, Scope: “Veil Mastery follows the design doc.” This retains once-per-session Echo conversion, gated behind Sovereign.

**Layer 4 — Archetype Resonance: Universal**
+1 to all skill checks when alone or no allies within earshot. The inverse of Aelora's community bonus. The Unbound are strongest self-reliant.

**Endgame Relevance**

When the Veythar reveal occurs:
- Patron-bonded characters process the truth through their god's reaction and filter
- The Unbound process it without divine mediation — their Veil Clarity shows the actual damage
- If the endgame involves reaching the Wellspring, the Unbound can interact with raw creative energy without a divine agenda coloring the experience
- The Unbound path is the hardest early game (no safety net) and most rewarding late game (complete autonomy, perfect awareness, unique endgame access)

---

### Patron System Summary

| God | Domain | Divine Gift | Resonance Modifier | Exalted Ability |
|---|---|---|---|---|
| Veythar | Knowledge | Reroll failed knowledge checks | Flickering bonus +2 dice (more reward, same risk) | Free spell, double Resonance |
| Kaelen | War | +2 atk/saves when below 25% HP | Combat spells -1 Resonance | Mark Worthy Foe, all attacks advantage |
| Aelora | Civilization | +1 skill checks near allies | No Veil Ward damage/DC penalty | Sanctuary zone, healing + protection |
| Thyra | Nature | Advantage Perception/Survival in nature | -1 Resonance on natural ground | 3d8 terrain damage, no save |
| Syrath | Shadows | 1-round invisibility | -2 Resonance from stealth | See through the Veil for 6 seconds |
| Orenthel | Healing | Heal others → self-heal 2 HP | Healing = 0 Resonance | Auto-stabilize fallen ally at half HP |
| Valdris | Justice | Compel NPC to acknowledge truth | Half Resonance on justified spells | Combat judgment (4d8 radiant + survivor stun if unjust, 2d8 radiant to follower if just) |
| Mortaen | Death | Sense creatures below 25% HP | 0 Resonance on 0 HP targets | Incorporeal for 1 round |
| Nythera | Exploration | Always know direction and distance | -1 Resonance in new locations | Gateway to visited location |
| Zhael | Fate | Force reroll any d20 | Choose between 2 Echo results | Undo 1 round of time (8 Resonance) |
| **Unbound** | Self | Know exact Resonance number | Voluntary +3 Resonance on demand | At Sovereign, first Hollow Echo per session becomes "Nothing stirs" |
