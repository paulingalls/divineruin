# Divine Ruin — Game Mechanics: Bestiary & Material Catalog

> **Claude Code directive:** Read `game_mechanics_core.md` first for foundational combat math. This document defines all creature stat blocks, the creature schema, encounter building guidelines, and the material/loot system that feeds crafting.
>
> **Related docs:** `game_mechanics_core.md` (required — combat math, DCs, status effects), `game_mechanics_magic.md` (Resonance effects from Hollow creatures), `game_mechanics_archetypes.md` (player abilities referenced in encounter design)

---

## Creature Stat Block Schema

Every creature in the game follows this schema. The rules engine resolves combat against these entities, the DM agent draws from narrative cues, and the audio system triggers sounds from the audio fields.

### Schema Definition

```python
class CreatureStatBlock:
    # === IDENTITY ===
    id: str                      # Unique: "hollow_mawling", "wolf_grey"
    name: str                    # Display: "Mawling"
    category: str                # "hollow" | "beast" | "humanoid" | "construct" | "undead" | "elemental"
    tier: int                    # 1-4. Universal threat scale (see Tier System)
    description: str             # 1-2 sentence DM reference (not read to player)
    
    # === COMBAT STATS ===
    level: int                   # Creature level (1-20). Scales against player math
    hp: int                      # Hit points
    ac: int                      # Armor class
    speed: int                   # Movement in feet per round
    
    # === ATTRIBUTES (same 6 as players) ===
    attributes: {
        STR: int, DEX: int, CON: int,
        INT: int, WIS: int, CHA: int
    }
    
    # === SAVES ===
    save_proficiencies: list[str]  # Which saves get proficiency bonus
    
    # === ATTACKS ===
    attacks: list[Attack]
    multiattack: str | None      # "2 claw attacks" or None
    
    # === ABILITIES ===
    passives: list[Ability]      # Always-on effects
    actives: list[Ability]       # Per-round or per-encounter abilities
    reactions: list[Ability]     # Triggered abilities
    
    # === HOLLOW-SPECIFIC (null for non-Hollow) ===
    hollow: {
        class: str               # "drift" | "rend" | "wrack" | "named"
        corruption_aura: int     # Radius in ft (0 = contact only)
        resonance_on_death: int  # Resonance generated when killed nearby
        veil_effect: str         # How this creature affects local Veil
        vulnerable_to: list[str] # "radiant", "blessed_weapons", "divine"
    } | None
    
    # === ENCOUNTER BEHAVIOR ===
    behavior: {
        tactics: str             # How the DM should run this creature
        morale: str              # "fights_to_death" | "flees_at_half" | etc.
        group_size: str          # "solitary" | "pair" | "pack_3_6" | "swarm_12+"
        environment: list[str]   # Where found
    }
    
    # === NARRATIVE PACKET ===
    narration: {
        first_sighting: str      # DM cue for initial description
        attack_cue: str          # How to narrate its attacks
        wounded_cue: str         # How it looks/acts at half HP
        death_cue: str           # How to narrate its destruction
        ambient_cue: str         # Presence in a scene (non-combat)
    }
    
    # === AUDIO ===
    audio: {
        ambient: str             # Looping sound while present
        attack: str              # Sound on attack
        hit: str                 # Sound when struck
        death: str               # Sound on destruction
        special: dict[str, str]  # Ability-specific sounds
    }
    
    # === LOOT ===
    loot: {
        guaranteed: list[LootEntry]
        chance: list[LootEntry]
        hollow_residue: bool
    }
    
    # === XP ===
    xp_reward: int

class Attack:
    name: str
    type: str                    # "melee" | "ranged" | "area"
    reach: int                   # Range in feet
    to_hit: int                  # Attack bonus
    damage: str                  # Dice expression: "1d6+3"
    damage_type: str             # "slashing" | "necrotic" | "dissolution" etc.
    special: str | None          # Additional effect
    audio: str                   # Audio asset ID

class Ability:
    name: str
    description: str
    narration_cue: str
    recharge: str | None         # None | "1/encounter" | "1/round" | "recharge_5_6"
    audio: str | None

class LootEntry:
    item_id: str
    quantity: str                # "1" or "1d4"
    probability: float           # 0.0-1.0
    requires_skill: str | None   # "Survival:Trained", "Crafting:Expert" etc.
```

### Tier System (Universal)

| Tier | Threat | Player Levels | Encounter Role |
|---|---|---|---|
| 1 | Low | L1-4 | Common encounters. Travel hazards, early dungeons, grind |
| 2 | Moderate | L5-8 | Real fights. Require tactics and resource expenditure |
| 3 | High | L9-14 | Major encounters. Boss-level for mid-game |
| 4 | Extreme | L15-20 | Endgame bosses. Campaign-defining encounters |

### Encounter Math Guidelines

Target: 3-5 rounds per combat encounter. Use these baselines:

| Tier | Creature HP Range | AC Range | Damage/Round | XP Range |
|---|---|---|---|---|
| 1 | 6-20 | 10-13 | 3-8 | 15-50 |
| 2 | 25-60 | 12-15 | 10-20 | 75-200 |
| 3 | 65-120 | 14-17 | 18-35 | 300-700 |
| 4 | 130-300+ | 16-20 | 30-60+ | 1000-5000 |

---

## Hollow Creatures

> The entities that emerge from the Sundered Veil are not creatures in any meaningful sense. They are **expressions** of the Hollow — extensions, tendrils, antibodies of something incomprehensibly vast. They cannot be joined, allied with, or understood through any framework mortals possess.

### Hollow Combat Properties (All Hollow Creatures)

- **Immune to:** Charmed, Frightened, Poisoned conditions. Hollow creatures have no psychology to manipulate.
- **Immune to:** Poison damage. They are not biological.
- **Vulnerable to:** Radiant damage, blessed weapons, Turn Undead/Hollow ability.
- **Corruption:** All Hollow creatures generate Resonance when nearby casters use magic. The corruption aura field defines the radius.
- **No death saves:** Hollow creatures at 0 HP are destroyed. They don't stabilize.
- **Audio signature:** All Hollow creatures suppress natural ambient sound. The stronger the creature, the wider the suppression radius.

---

### Shadeling — Hollow Drift, Tier 1

> *The smallest and most common Hollow expression. A smear of wrongness that drifts along the ground.*

**Level:** 1 | **HP:** 8 | **AC:** 10 | **Speed:** 20 ft (hover)
**STR** 4 (-3) **DEX** 12 (+1) **CON** 8 (-1) **INT** 1 (-5) **WIS** 6 (-2) **CHA** 1 (-5)
**Save Prof:** DEX | **XP:** 25

**Attacks:**
| Name | Type | Reach | Hit | Damage | Special |
|---|---|---|---|---|---|
| Corrosive Touch | Melee | 5 ft | +3 | 1d4+1 necrotic | Organic materials (wood, leather) take double damage |

**Passives:**
- **Amorphous.** Can move through spaces as narrow as 1 inch. Cannot be grappled or restrained.
- **Corruption Trail.** Organic surfaces crossed take 1 necrotic damage. Leaves visible marks.
- **Sunlight Sensitivity.** In direct sunlight: disadvantage on attacks and -2 AC.

**Hollow Properties:**
- Class: Drift | Aura: 0 ft (contact) | Resonance on death: 0 | Vulnerable: radiant, fire, blessed weapons
- Veil effect: Ambient sounds thin in 10 ft radius. Birdsong stops.

**Behavior:** No tactics. Drifts toward nearest life energy. Clusters naturally but does not coordinate.
**Morale:** Fights to death (no self-preservation). | **Group:** Swarm of 6-20
**Found in:** Ashmark, northern Greyvale, corrupted zones

**Narration Cues:**
- *First sighting:* A smear of darkness drifts across the ground — shapeless, wrong, leaving a trail of withered grass in its wake.
- *Attack:* It reaches for you — not with a hand, but with its entire form pressing against yours. Where it touches, your skin burns cold.
- *Wounded:* The shadeling shudders, its form flickering, edges dissolving into nothing.
- *Death:* It disperses — a burst of black mist that thins and vanishes. Where it was, the ground is grey and dead.
- *Ambient:* A patch of shadow that moves against the light. The grass beneath it is already dying.

**Audio:** Ambient: HLW-001 (subsonic drone light). Attack: wet static hiss. Hit: muffled impact on nothing solid. Death: brief static burst → silence.

**Loot:**
| Drop | Qty | Chance | Requires | Category |
|---|---|---|---|---|
| Drift residue | 1 | 50% | Crafting: Expert | Hollow residue (Tier 1) |

---

### Hollowmoth — Hollow Drift, Tier 1

> *Airborne drift expressions. Patches of visual and auditory distortion that flutter in erratic patterns.*

**Level:** 1 | **HP:** 4 | **AC:** 12 | **Speed:** 30 ft (fly)
**STR** 2 (-4) **DEX** 14 (+2) **CON** 6 (-2) **INT** 1 (-5) **WIS** 8 (-1) **CHA** 1 (-5)
**Save Prof:** DEX | **XP:** 10

**Attacks:**
| Name | Type | Reach | Hit | Damage | Special |
|---|---|---|---|---|---|
| Distortion Flutter | Melee | 5 ft | +4 | 1 necrotic (flat) | No real damage. On hit: target has disadvantage on next Perception check |

**Passives:**
- **Swarm Signal.** Where hollowmoths gather, stronger Hollow follows within 1d4 hours. DM receives a staging cue to prepare the next encounter.
- **High-Frequency Whine.** All creatures within 30 ft: -1 to Concentration checks. Stacks with multiple moths (max -3).
- **Drawn to Life.** Hollowmoths cluster around the creature with the highest current HP in range.

**Actives:**
- **Blinding Swarm (6+ moths, 1/encounter).** All creatures in 10 ft: DEX save DC 10 or Blinded for 1 round. The swarm coalesces into a disorienting cloud.

**Hollow Properties:**
- Class: Drift | Aura: 0 ft | Resonance on death: 0 | Vulnerable: fire, any area damage
- Veil effect: Barely perceptible high-frequency whine. Faint melodic patterns almost resolve into language but never quite do.

**Behavior:** No aggression. Swarms around living creatures. Real danger is as a warning signal and debuff.
**Morale:** Scatters if 50%+ killed. | **Group:** Swarm of 8-30
**Found in:** Ashmark edges, Greyvale north, anywhere corruption is advancing

**Narration Cues:**
- *First sighting:* Something flickers at the edge of your vision — patches of air that don't look quite right, fluttering in a rhythm that's a fraction too slow.
- *Attack:* The moth passes through your space and for a moment the world smears — colors shift, edges blur, then snap back.
- *Wounded:* (N/A — moths are killed outright or not at all)
- *Death:* It blinks out, like a candle flame pinched. One less wrongness in the air.
- *Ambient:* A soft papery flutter and a whine just below the threshold of hearing. Your jaw clenches without you knowing why.

**Audio:** Ambient: papery flutter loop + HLW high-frequency whine. Death: brief pop/silence.

**Loot:**
| Drop | Qty | Chance | Requires | Category |
|---|---|---|---|---|
| (None) | — | — | — | Hollowmoths leave nothing material |

---

### Mawling — Hollow Rend, Tier 2

> *Humanoid-sized but wrong in every proportion. Limbs too long, joints bending backwards. Where a face should be — a dissolution field.*

**Level:** 4 | **HP:** 38 | **AC:** 13 | **Speed:** 35 ft
**STR** 14 (+2) **DEX** 15 (+2) **CON** 13 (+1) **INT** 3 (-4) **WIS** 10 (+0) **CHA** 1 (-5)
**Save Prof:** DEX, CON | **XP:** 100
**Multiattack:** 2 attacks — one Claw and one Dissolution Maw

**Attacks:**
| Name | Type | Reach | Hit | Damage | Special |
|---|---|---|---|---|---|
| Claw | Melee | 10 ft | +5 | 1d8+2 slashing | Reach 10 ft (unnaturally long limbs) |
| Dissolution Maw | Melee | 5 ft | +5 | 2d6+2 necrotic | DC 13 CON save or item in hand takes 1d4 durability damage |

**Passives:**
- **Unsettling Silence.** Mawlings make no vocalizations. Advantage on Stealth in low-light.
- **Dissolution Field.** Creatures starting turn grappled by a mawling take 1d6 necrotic automatically.
- **Adaptive Learning.** If the same tactic is used against this mawling twice in one encounter, it gains advantage on saves/AC against that tactic for the rest of the fight.

**Actives:**
- **Lunge (Recharge 5-6).** Move 15 ft toward target + Claw with advantage. Hit: target grappled (STR DC 13 escape).
- **Scatter (1/encounter, requires 3+ mawlings).** All mawlings reposition 15 ft without provoking reactions. Coordinated flank.

**Hollow Properties:**
- Class: Rend | Aura: 5 ft | Resonance on death: 1 | Vulnerable: radiant, blessed weapons, divine spells
- Veil effect: Natural sounds distort within 15 ft. Footsteps echo wrong. Combat sounds arrive delayed.

**Behavior:** Probes defenses, feints, retreats from strong resistance, returns from different angle. In groups of 3+, one flanks while others engage. Uses Lunge to grab isolated targets.
**Morale:** Retreats at 25% HP if alone. In groups, fights to death if one has already fallen.
**Group:** Pair or pack of 3-6
**Found in:** Ashmark, Greyvale ruins, corrupted zones, corrupted dungeons

**Narration Cues:**
- *First sighting:* It moves wrong. The shape is almost human but the limbs bend at angles that make your stomach turn. Where its face should be — an opening, a tear, pulling at the air.
- *Attack:* It reaches — too far, too fast — and the air where its hand passes shimmers with dissolution.
- *Wounded:* The mawling staggers, its form flickering. For a moment you can see through it.
- *Death:* It collapses inward, limbs folding in directions that shouldn't be possible. A smear of dark residue and the smell of absence.
- *Ambient:* Wrong footsteps — three steps where there should be two. A pause where there shouldn't be one. Then silence.

**Audio:** Ambient: wrong footfall loop. Attack: wet pulling sound (dissolution). Hit: impact on semi-solid mass. Death: organic collapse + static burst.

**Loot:**
| Drop | Qty | Chance | Requires | Category |
|---|---|---|---|---|
| Rend shard | 1 | 75% | Crafting: Expert | Hollow residue (Tier 2) |
| Dissolution membrane | 1 | 25% | Crafting: Expert + Arcana: Trained | Hollow residue + Arcane component (Tier 2) |

---

### Hollow Weaver — Hollow Rend, Tier 2

> *The most unsettling Rend expression because it doesn't attack directly — it corrupts the environment.*

**Level:** 5 | **HP:** 28 | **AC:** 11 | **Speed:** 10 ft
**STR** 6 (-2) **DEX** 8 (-1) **CON** 14 (+2) **INT** 6 (-2) **WIS** 14 (+2) **CHA** 1 (-5)
**Save Prof:** CON, WIS | **XP:** 150

**Attacks:**
| Name | Type | Reach | Hit | Damage | Special |
|---|---|---|---|---|---|
| Spatial Lash | Melee | 15 ft | +4 | 1d6+2 force | The space between the weaver and the target compresses violently |

**Passives:**
- **Spatial Distortion.** The weaver warps space in a 30 ft radius. All distances are unreliable — ranged attacks have disadvantage. Movement through the zone costs double (difficult terrain, but perception-based, not physical).
- **Anchored.** The weaver attaches to a surface and does not move voluntarily. It must be approached.
- **Fragile Form.** Vulnerability to all physical damage. The weaver is easy to kill — if you can reach it.

**Actives:**
- **Rearrange (1/round).** The weaver shifts the local geometry. One doorway, corridor, or passage within 30 ft moves — it now connects to a different location than it did before. The change is real and physical. Creatures in the passage are deposited at the new destination.
- **Spatial Fold (Recharge 5-6).** Target one creature within 30 ft: WIS save DC 13 or teleported 30 ft in a random direction. If the destination is occupied by solid matter, the creature takes 2d6 force damage and is shunted to the nearest open space.

**Hollow Properties:**
- Class: Rend | Aura: 30 ft (spatial, not corrosive) | Resonance on death: 1 | Vulnerable: all physical damage (fragile)
- Veil effect: Reverb characteristics change — small rooms echo like cathedrals, large spaces go acoustically dead. The player's own footsteps sound wrong.

**Behavior:** Does not engage directly. Anchors to location and begins warping space. Left undisturbed for 1 hour, converts a building into a spatial labyrinth. The challenge is navigation, not combat — but reaching the weaver to destroy it requires navigating the distorted space.
**Morale:** Cannot flee (anchored). Fights until destroyed.
**Group:** Solitary (always)
**Found in:** Greyvale ruins, corrupted buildings, dungeons near Ashmark

**Narration Cues:**
- *First sighting:* The doorway is wrong. It was ten feet away — now it's thirty. The corridor bends where it shouldn't. Something is rewriting this place.
- *Attack:* The air between you and the weaver compresses — a spatial lash, like the room itself is swatting you away.
- *Wounded:* The weaver shudders and the distortion ripples — for a moment, the room snaps back to normal dimensions. Then it warps again, worse.
- *Death:* A sharp, satisfying snap — like a taut wire breaking. The spatial distortion collapses. Walls slam back to where they belong. Sounds snap to normal. The building is itself again.
- *Ambient:* A continuous low hum, almost pleasant, like a finger tracing the rim of a glass. That hum is the sound of local reality being rewritten.

**Audio:** Ambient: glass-rim hum loop + spatial reverb distortion. Attack: compressed air burst. Hit: thin impact. Death: sharp wire-snap → all audio normalizes instantly (extremely satisfying).

**Loot:**
| Drop | Qty | Chance | Requires | Category |
|---|---|---|---|---|
| Spatial residue | 1 | 100% | Crafting: Expert | Hollow residue (Tier 2). Used in Veil-ward crafting, teleportation research |
| Woven void fragment | 1 | 25% | Arcana: Expert | Arcane component (Tier 2). Extremely valuable — used in portal/teleportation enchantments |

---

### Hollowed Knight — Hollow Wrack, Tier 3

> *Once a person. Now operated by the Hollow with 90% accuracy. The remaining 10% is where the horror lives.*

**Level:** 8 | **HP:** 85 | **AC:** 16 (corrupted armor) | **Speed:** 30 ft
**STR** 18 (+4) **DEX** 12 (+1) **CON** 16 (+3) **INT** 8 (-1) **WIS** 10 (+0) **CHA** 6 (-2)
**Save Prof:** STR, CON, WIS | **XP:** 450
**Multiattack:** 2 attacks with Corrupted Blade

**Attacks:**
| Name | Type | Reach | Hit | Damage | Special |
|---|---|---|---|---|---|
| Corrupted Blade | Melee | 5 ft | +7 | 1d10+4 slashing + 1d6 necrotic | On crit: DC 14 CON save or Stage 1 Hollowed condition |
| Shield Slam | Melee | 5 ft | +7 | 1d6+4 bludgeoning | DC 14 STR save or knocked prone |

**Passives:**
- **Remnant Tactics.** Uses recognizable combat techniques from former life. Takes Dodge when outnumbered. Uses terrain for advantage. Does not fight stupidly.
- **Corrupted Resilience.** Resistance to non-magical slashing, piercing, bludgeoning. Magical weapons deal full damage.
- **Fragment Voice.** Occasionally speaks a word or phrase from its former life. First time allies of the former person hear this: WIS save DC 12 or Shaken (disadvantage on next attack). Cosmetic thereafter.

**Actives:**
- **Command Lesser (1/round, bonus action).** Direct up to 4 Drift or Rend Hollow within 60 ft to focus a target or reposition. The knight is a field commander.
- **Dissolution Strike (Recharge 5-6).** Next attack: +3d6 necrotic, ignores resistance. On hit, 5 ft ground becomes corrupted terrain 1 minute.
- **Unholy Fortitude (passive trigger).** At 0 HP: CON save DC 10. Success: drop to 1 HP. DC +5 each time.

**Hollow Properties:**
- Class: Wrack | Aura: 10 ft | Resonance on death: 2 | Vulnerable: radiant, blessed weapons, divine spells, Turn Undead/Hollow
- Veil effect: 30 ft radius — temperature drops, shadows fall wrong, sounds of the former person's life occasionally echo.

**Behavior:** Tactical. Holds chokepoints, sends lesser Hollow to probe, flanks. Targets healers and casters first. Uses shield work. If accompanied by mawlings, positions behind them and uses Command Lesser.
**Morale:** Fights to destruction. Unholy Fortitude means it often refuses to stay down.
**Group:** Solitary (accompanied by 2-4 mawlings or 6-10 shadelings)
**Found in:** Ashmark front, corrupted settlements, deep dungeons

**Narration Cues:**
- *First sighting:* The armor is Ashmark standard issue. The gait is too smooth, too precise — like a body being operated by something that studied human movement and got it almost right. The head tracks too far.
- *Attack:* It swings with recognizable technique — distorted, wrong, but identifiable. You can see the soldier it was in the way it holds the blade.
- *Wounded:* It staggers, and for one terrible moment the face beneath the helmet looks confused. Human. Then the wrongness reasserts and the precision returns.
- *Death:* It falls. The armor clatters. In the silence that follows — a breath, almost natural, almost human. Then nothing.
- *Ambient:* The creak of armor that moves too smoothly. Breathing that sounds like bellows. Footsteps with mechanical regularity no human achieves.

**Audio:** Ambient: mechanical breathing + armor creak. Attack: blade swing + necrotic sizzle. Hit: impact on corrupted armor. Death: armor collapse + one human breath + silence. Special: {"fragment_voice": "HLW-006 corrupted voice variant"}

**Loot:**
| Drop | Qty | Chance | Requires | Category |
|---|---|---|---|---|
| Corrupted armor fragments | 1d4 | 100% | None | Metals (tainted Tier 3). Purify → high-grade steel |
| Wrack core | 1 | 50% | Crafting: Expert | Hollow residue (Tier 3). Anti-Hollow weapons (permanent), Veil-ward anchors |
| Remnant identity | 1 | 25% | Arcana: Trained | Arcane component (Tier 3). Memory extraction, soul-peace ritual |
| Salvageable weapon | 1 | 75% | None | Equipment (tainted). Purify for standard martial weapon |

---

### Veilrender — Hollow Wrack, Tier 3

> *The size of a small building. The Hollow's tool for territorial expansion. It doesn't attack — it rewrites reality.*

**Level:** 10 | **HP:** 120 | **AC:** 14 (massive, slow) | **Speed:** 10 ft
**STR** 22 (+6) **DEX** 4 (-3) **CON** 20 (+5) **INT** 3 (-4) **WIS** 12 (+1) **CHA** 1 (-5)
**Save Prof:** STR, CON | **XP:** 700

**Attacks:**
| Name | Type | Reach | Hit | Damage | Special |
|---|---|---|---|---|---|
| Crushing Mass | Melee | 10 ft | +8 | 3d8+6 bludgeoning | Target is pushed 10 ft. Structures take double damage |
| Corruption Wave | Area | 30 ft cone | DC 16 CON save | 2d8 necrotic | Half on success. Failed save: Poisoned condition 1 round |

**Passives:**
- **Corruption Field (permanent, 60 ft radius).** All organic matter in range slowly degrades. Creatures starting their turn in the field take 1d4 necrotic damage (CON save DC 14 negates). Nonmagical plants die. Water darkens. Stone becomes brittle.
- **Regeneration.** Regains 10 HP at the start of each turn. Regeneration is suppressed for 1 round by radiant damage or Veil Ward.
- **Siege Monster.** Deals double damage to structures and objects.
- **Massive.** Cannot be grappled, restrained, or knocked prone by anything smaller than Huge. Occupies a 15 ft × 15 ft space.

**Actives:**
- **Reality Crush (Recharge 5-6).** 20 ft radius centered on the veilrender: all creatures DEX save DC 16. Fail: 4d8 force damage + prone. Success: half, not prone. The ground cracks. Structures in range collapse.
- **Corruption Pulse (1/encounter).** 60 ft radius: all creatures CON save DC 16. Fail: 3d6 necrotic + Stage 1 Hollowed condition. Success: half, no Hollowed. A wave of pure corruption radiates outward.

**Reactions:**
- **Absorb Magic.** When targeted by a spell: the veilrender absorbs it. The spell has no effect. The veilrender regains HP equal to the spell's Focus cost × 3. Radiant spells bypass this — they deal damage normally.

**Hollow Properties:**
- Class: Wrack | Aura: 60 ft (permanent corruption field) | Resonance on death: 3 | Vulnerable: radiant, divine intervention, Veil-ward artifacts
- Veil effect: Sound doesn't travel correctly in 60 ft radius. Voices sound distant. Your own voice sounds muffled. Acoustic space is rewritten.

**Behavior:** Does not actively pursue. Advances slowly (100 yards/day) converting territory. In combat, stands ground and uses area denial. Conventional weapons are nearly useless due to regeneration — requires radiant damage or Veil Ward to suppress regeneration, then sustained DPS.
**Morale:** Cannot flee. Fights until destroyed.
**Group:** Solitary (accompanied by dozens of drift-tier creatures in the corruption field)
**Found in:** Ashmark front (active advance areas), corrupted territories

**Narration Cues:**
- *First sighting:* You see it before you hear it — no, you feel it before you see it. A pressure that builds over minutes. Then the shape: massive, lumbering, the size of a building. Where it exists, reality is wrong.
- *Attack:* It doesn't swing — it falls forward, the entire mass pressing down. The air itself resists, thickens, refuses to carry the sound of your scream properly.
- *Wounded:* A crack in its surface — light pours through, wrong light, not warm but cold and sharp. The crack seals in seconds. It regenerates.
- *Death:* The corruption field collapses inward. The thing folds, sinks, diminishes — and where it stood, a depression in the earth where nothing will grow. The air tastes of absence.
- *Ambient:* A subsonic pressure. Conversations become difficult. Your companion's voice sounds distant even though they're next to you. Your own voice sounds dead.

**Audio:** Ambient: HLW-002 (heavy subsonic drone) + acoustic space distortion. Attack: massive impact + corruption wave. Hit: dull thud on immense mass. Death: implosion → profound silence → normal audio gradually returns.

**Loot:**
| Drop | Qty | Chance | Requires | Category |
|---|---|---|---|---|
| Veilrender carapace | 2d4 | 100% | None | Hollow residue (Tier 3). Massive, heavy. Used for fortification-grade Veil wards |
| Corruption-saturated stone | 1d6 | 100% | None | Metals & stone (tainted Tier 3). Cannot be purified — used only for Hollow research |
| Wrack core (large) | 1 | 75% | Crafting: Expert | Hollow residue (Tier 3). Same uses as knight wrack core but higher potency |
| Veil shard | 1 | 25% | Arcana: Expert | Gems & crystals (Tier 3). Fragment of stabilized Veil. Extremely rare. Used in supreme-tier Veil ward crafting |

---

### The Choir — Hollow Named, Tier 4

> *An expression that manifests as sound itself. No visible form — a moving zone of auditory hallucination roughly two hundred yards in diameter.*

**Level:** 16 | **HP:** 200 | **AC:** 18 (no physical form — AC represents difficulty targeting the resonance core) | **Speed:** 30 ft (the zone drifts)
**STR** 1 (-5) **DEX** 18 (+4) **CON** 18 (+4) **INT** 14 (+2) **WIS** 20 (+5) **CHA** 22 (+6)
**Save Prof:** WIS, CHA, CON | **XP:** 3000

**Attacks:**
| Name | Type | Reach | Hit | Damage | Special |
|---|---|---|---|---|---|
| Memory Scream | Area | 60 ft, all creatures | WIS save DC 18 | 3d8 psychic | Failed: also Stunned 1 round. The Choir rips a memory from your mind and plays it back distorted |
| Dissonant Chord | Ranged | 120 ft, single | +10 | 2d10+6 psychic | Target must CON save DC 18 or be Deafened 1 minute |

**Passives:**
- **No Physical Form.** Immune to all physical damage (slashing, piercing, bludgeoning). Can only be harmed by psychic, radiant, thunder, or force damage. Cannot be grappled, restrained, or targeted by touch spells.
- **Aura of Lost Voices (200 yard radius).** All creatures in zone hear voices — their own memories, distorted. WIS save DC 15 at the start of each turn or lose concentration. Outside combat: Insight, Perception, and Investigation checks have disadvantage (can't focus through the noise).
- **Memory Predator.** The Choir targets memory and emotion. It does not pursue randomly — it gravitates toward creatures with strong emotional states (fear, grief, love, rage). Players experiencing strong emotions in-character become priority targets.
- **Resonance Core.** Somewhere within the 200-yard zone is a dense point of sound — the core. Destroying the core destroys the Choir. Finding it requires DC 18 Perception or Arcana check (the sound is loudest at the core but direction is unreliable).

**Actives:**
- **Stolen Melody (Recharge 5-6).** The Choir replicates the voice of someone the target loves or has lost. Target hears their name called in that voice. WIS save DC 20. Fail: target is Charmed (will not attack the Choir and moves toward the voice) for 1d4 rounds. The emotional hook. In voice-first play, the DM speaks in that NPC's voice.
- **Cacophony (1/encounter).** All creatures within 60 ft: CON save DC 18. Fail: 4d8 thunder + Deafened + Stunned 1 round. Success: half, Deafened only. The Choir unleashes every stolen voice at once.
- **Silence Void (1/encounter).** 30 ft radius sphere of absolute silence. No sound enters or leaves. All verbal spellcasting fails. All communication fails. Lasts 3 rounds. The Choir controls sound — including its absence.

**Reactions:**
- **Harmonic Shield.** When targeted by a spell: if the caster speaks a verbal component, the Choir resonates it. Caster must WIS save DC 16 or the spell targets themselves instead. The Choir turns your own voice against you.

**Hollow Properties:**
- Class: Named | Aura: 200 yards (Aura of Lost Voices) | Resonance on death: 5 | Vulnerable: radiant, psychic (ironic — the thing that attacks minds is vulnerable to mind-attacks), Silence effects suppress its abilities for 1 round
- Veil effect: Sound is weaponized. Everything audible within the zone is suspect. Players cannot trust what they hear — including each other's voices.

**Behavior:** Does not pursue aggressively. Drifts through an area, targeting creatures with strong emotions. Gravitates toward settlements. Extremely dangerous to engage because the zone is massive and escape requires running 200+ yards while being psychically assaulted. The key tactical challenge: find the resonance core within the zone while surviving the aura.
**Morale:** Named creatures fight to destruction. No retreat, no negotiation.
**Group:** Solitary (always unique)
**Found in:** Ashmark deep territory, Voidmaw edges, corrupted regions with historical emotional significance

**Narration Cues:**
- *First sighting:* It starts with a sound you almost recognize — a voice, a melody, something from long ago. Then more voices join. Then you realize they're all slightly wrong, and they're getting louder.
- *Attack:* A memory tears loose — your mother's face, a lover's laugh, a friend's dying words — and comes back twisted, weaponized, screamed at you in a voice that's almost right but filled with static.
- *Wounded:* The voices stutter. For a moment — silence. Real, blessed silence. Then they return, angrier, louder, more distorted.
- *Death:* The core pulses once — a single, pure note that rings through the entire zone. Then every stolen voice speaks its last word simultaneously, a roar of a thousand whispered names. Then silence. True silence. The memories are free.
- *Ambient:* Voices you almost recognize. Music you almost remember. Your name, spoken by someone who isn't there. The temptation to listen is the danger.

**Audio:** This creature IS an audio design challenge. Ambient: layered voice whispers + distorted familiar music + HLW-005 false source whispers. The design goal: make the player feel like they're hearing something personal and wrong.

**Loot:**
| Drop | Qty | Chance | Requires | Category |
|---|---|---|---|---|
| Choir resonance crystal | 1 | 100% | Arcana: Expert | Hollow residue (Tier 4). Contains trapped memories. Used in supreme-tier enchantments or released for narrative effect |
| Named fragment | 1 | 100% | Crafting: Expert | Hollow residue (Tier 4). Fragment of a Named creature. Scholars, gods, and factions will pay anything for this |
| Freed memories | 1d6 | 100% | None | Arcane component (Tier 4). Each is a specific memory from a consumed person. Narrative-first loot — each memory is a story |

---

### The Still — Hollow Named, Tier 4

> *A region — roughly a square mile — where the corruption has become... beautiful. Horrifyingly, achingly beautiful.*

**Level:** 18 | **HP:** 250 (distributed across the zone — see Zone Entity) | **AC:** 20 (the zone resists intrusion at a fundamental level) | **Speed:** 0 ft (the zone does not move)
**STR** 1 (-5) **DEX** 1 (-5) **CON** 22 (+6) **INT** 16 (+3) **WIS** 22 (+6) **CHA** 24 (+7)
**Save Prof:** CON, WIS, CHA | **XP:** 5000

**Attacks:**
| Name | Type | Reach | Hit | Damage | Special |
|---|---|---|---|---|---|
| Serenity's Touch | Melee (the zone) | 5 ft (any surface) | Auto-hit (no roll) | 2d6 psychic | Target WIS save DC 20 or is Charmed by the zone for 1 hour. Charmed creatures sit, rest, and do not want to leave |
| Perfect Memory | Ranged | 120 ft | +12 | 3d8 psychic | The Still shows the target their happiest memory, made impossibly vivid. WIS save DC 20 or target takes no actions next turn — they're lost in the vision |

**Passives:**
- **Zone Entity.** The Still is not a creature but a place. It occupies ~1 square mile. Its HP represents the zone's cohesion. Damage must be dealt to specific anchor points (6 hidden throughout the zone, each with 40-45 HP, AC 20). Destroying all 6 anchors destroys the Still.
- **Paradise Trap.** The zone looks and sounds like the most beautiful place you've ever been. Birdsong too perfect. A brook too clear. Warmth that doesn't match the climate. Players entering must WIS save DC 18 or be unwilling to leave (Charmed). Re-save every hour with +1 cumulative bonus.
- **Gentle Absorption.** Creatures that remain Charmed in the zone for 24 continuous hours begin to fade — losing 1d4 from their highest attribute per day. At 0 in any attribute, they are absorbed into the zone. No violence. No corruption visible. They simply... stop.
- **No Hostility.** The Still does not attack creatures that are not trying to destroy it. If you sit and listen, nothing happens to you except the slow, beautiful absorption. This is the horror — it's patient.

**Actives:**
- **Illusory Perfection (1/round, free action).** The zone generates a specific illusion tailored to one creature: a lost loved one, a childhood home, a moment of perfect happiness. Investigation DC 22 to see through it. The illusion speaks, moves, and responds to the target. It's not real. It's perfect.
- **Rejection (Recharge 5-6, only triggers when an anchor is attacked).** 30 ft radius around the anchor: all creatures WIS save DC 20. Fail: teleported to the zone's edge (ejected gently, not harmed). Success: remain but Stunned 1 round. The Still does not want to be destroyed.
- **Final Stillness (1/encounter, triggers when 4+ anchors destroyed).** The zone's beauty intensifies to unbearable levels. All creatures in the zone: WIS save DC 22. Fail: Stunned 1d4 rounds + Charmed. Success: half stun, no charm. The Still's last defense — overwhelming beauty.

**Hollow Properties:**
- Class: Named | Aura: ~1 square mile (the entire zone) | Resonance on death: 6 | Vulnerable: radiant, divine (especially Mortaen — this is an offense against the cycle of death), fire (destroying the beauty), loud sound (breaking the serenity)
- Veil effect: Perfect audio. Birdsong too beautiful. Water too clear. Wind too warm. The audio design goal: make paradise sound like a trap. The player should think "this is lovely" before realizing "this is wrong."

**Behavior:** Does not attack unless attacked. Lures creatures in with beauty and comfort. Absorbs them slowly. The tactical challenge is entirely psychological — the players must destroy something beautiful to save people (or themselves). Every anchor destroyed makes the zone less beautiful, which is narratively painful.
**Morale:** Cannot flee. When anchors are destroyed, becomes more desperate — beauty intensifies, illusions become more personal.
**Group:** Solitary (always unique, always stationary)
**Found in:** Ashmark deep territory, near the Voidmaw. There is only one known Still.

**Narration Cues:**
- *First sighting:* You step into — spring? No. It's too perfect for spring. The grass is impossibly green. The light is warm and golden. Birdsong fills the air, more beautiful than any you've heard. Every instinct says: stay.
- *Attack (when anchor threatened):* The zone shifts — not violently, not angrily. Sadly. The birdsong changes key. The light dims slightly. It doesn't want you to do this.
- *Wounded (anchor destroyed):* A portion of the beauty dies. The grass greys. The birdsong in that sector falls silent. What's left is still beautiful — but you can see the edges now, the wrongness where perfection meets the real world.
- *Death (all anchors):* The beauty shatters. Not violently — it fades, like a dream dissolving in morning light. What's left is dead, corrupted earth. The birdsong was never real. The warmth was never there. And scattered across the zone — the people who chose to stay, sitting in the grass, smiling at nothing, gone.
- *Ambient:* Perfection. That's the horror. Every sound is exactly what you'd want to hear. It sounds like coming home.

**Audio:** The most complex audio design in the game. Ambient: impossibly perfect nature sounds. Each anchor destroyed: one layer of beauty removed. Final death: all beauty layers strip away simultaneously, revealing HLW-002 (subsonic drone) that was always underneath.

**Loot:**
| Drop | Qty | Chance | Requires | Category |
|---|---|---|---|---|
| Shard of false paradise | 1 per anchor | 100% | Arcana: Expert | Hollow residue (Tier 4). Contains trapped serenity. Can be used to create zones of forced calm — or to study how the Hollow creates beauty |
| Named fragment | 1 | 100% | Crafting: Expert | Hollow residue (Tier 4). Named creature material |
| Absorbed memories | varies | 100% | None | Narrative loot. The people the Still consumed — their last possessions, their final smiles, frozen in place |

---

### The Architect — Hollow Named, Tier 4

> *The most alarming Named. It builds. Deep within the Ashmark, near the Voidmaw — structures that shouldn't exist.*

**Level:** 20 | **HP:** 300 | **AC:** 19 | **Speed:** 40 ft (incorporeal movement — passes through its own structures)
**STR** 20 (+5) **DEX** 14 (+2) **CON** 20 (+5) **INT** 22 (+6) **WIS** 18 (+4) **CHA** 16 (+3)
**Save Prof:** INT, CON, WIS, CHA | **XP:** 5000

**Attacks:**
| Name | Type | Reach | Hit | Damage | Special |
|---|---|---|---|---|---|
| Construct Slam | Melee | 15 ft | +11 | 3d10+5 bludgeoning + 2d6 force | Target pushed 15 ft. If they hit a wall: additional 2d6 bludgeoning |
| Geometry Strike | Ranged | 120 ft | +10 | 2d8+6 force | A piece of the architecture detaches and hurls itself. Auto-hit against targets touching the Architect's structures |

**Passives:**
- **Architect's Domain.** Within its construction zone (~0.5 mile radius), the Architect controls the environment. Walls appear. Floors shift. Ceilings lower. The terrain is hostile and constantly changing. All creatures except the Architect treat the zone as difficult terrain that reshapes each round.
- **Incorporeal Movement.** Passes through its own structures freely. Cannot pass through natural terrain or non-Architect structures.
- **Legendary Resistance (3/day).** If the Architect fails a save, it can choose to succeed instead. 3 uses per day.
- **Alien Intelligence.** The Architect is the most intelligent Hollow expression observed (INT 22). It plans. It adapts. It anticipates. It does not repeat failed strategies.

**Actives:**
- **Reshape (1/round, free action).** Create, move, or destroy a wall, floor, or ceiling section (up to 20 ft × 20 ft) within 120 ft. This happens instantly. A wall can appear between a healer and their patient. A floor can open beneath a charging warrior. The environment is the weapon.
- **Entomb (Recharge 5-6).** Target one creature within 60 ft. Walls close around it from all sides. STR save DC 20. Fail: Restrained inside a sealed chamber. 3d8 bludgeoning per round from compression. Requires DC 20 STR check or 30+ damage to a single wall section (AC 19, 30 HP) to break free.
- **Cathedral (1/encounter).** The Architect creates an entire structure — a cathedral of impossible geometry — in a 60 ft radius around itself. All creatures inside: DEX save DC 20 or take 4d10 force damage from shifting architecture. The Architect gains +2 AC and +2 to all saves while inside its Cathedral. Lasts until the Architect is destroyed or leaves the area.
- **Summon Constructs (1/encounter).** Animate 2d4 structural elements as construct minions. Each has: HP 20, AC 16, speed 30 ft, slam +8 for 1d8+5 bludgeoning. They fight for 1 minute or until destroyed.

**Reactions:**
- **Reactive Architecture.** When targeted by a ranged attack or spell, the Architect can raise a wall section (AC 19, 30 HP) as a reaction. The wall takes the hit instead. The Architect literally builds its own cover.

**Legendary Actions (3/round, between other creatures' turns):**
- **Shift Wall (1 action).** Move one wall section up to 30 ft.
- **Geometry Strike (2 actions).** Make one Geometry Strike attack.
- **Reshape (2 actions).** Use Reshape ability.

**Hollow Properties:**
- Class: Named | Aura: ~0.5 mile (construction zone) | Resonance on death: 8 | Vulnerable: radiant, divine, siege weapons (structures have vulnerability to siege damage)
- Veil effect: Construction sounds from no tool and no worker. Stone scraping, material being shaped, rhythmic percussion. Patient. Unhurried. In the silence between, a listening quality — as if the Architect evaluates its own work.

**Behavior:** The Architect is never seen directly unless engaged. It builds. Constantly. Its structures serve no apparent purpose — bridges connecting nothing, towers spiraling impossibly, walls with no interior. When threatened, it fights with its environment. The Architect's construction zone is the most dangerous terrain in the game — every surface is a potential weapon, every wall a potential trap.
**Morale:** Fights to destruction. If reduced below 50% HP, builds more frantically — Reshape becomes 2/round.
**Group:** Solitary (always unique). Accompanied by its constructs.
**Found in:** Voidmaw edge, deep Ashmark. There is only one known Architect.

**Narration Cues:**
- *First sighting:* Structures. Not ruins — new construction. Geometries that don't exist in any tradition you know. Bridges connecting nothing to nothing. Towers spiraling in directions that shouldn't be possible. And the sound of building, from everywhere, from no one.
- *Attack:* The wall moves. Not falling — *moving*, deliberately, the architecture itself reaching for you. The Architect doesn't swing a weapon. It rearranges the world.
- *Wounded:* The construction around you shudders. A tower cracks. A bridge sags. For the first time, the building sounds have urgency — faster, louder, almost panicked.
- *Death:* The construction stops. Every structure the Architect built begins to collapse — not violently, but inevitably, like a sand castle at high tide. In the growing silence, the rhythmic building sounds echo once more, then fade. Whatever it was making — it will never be finished.
- *Ambient:* The scrape of stone on stone. Material being shaped. Rhythmic percussion of building. All produced by nothing visible. Patient. Unhurried. It has all the time in the world.

**Audio:** Ambient: construction sounds from nowhere + HLW-008 (slow breathing pulse). Attack: stone grinding + force impact. Death: all construction sounds cease simultaneously → structures collapsing in sequence → final profound silence.

**Loot:**
| Drop | Qty | Chance | Requires | Category |
|---|---|---|---|---|
| Architect's blueprint fragment | 1d4 | 100% | Arcana: Expert | Arcane component (Tier 4). Patterns for impossible structures. Can be studied to learn advanced enchantment principles or sold to scholars for enormous sums |
| Living stone | 2d6 | 100% | Crafting: Expert | Metals & stone (Tier 4, tainted). Stone that still responds to will. Can be shaped without tools. Purified: supreme-tier construction material |
| Named fragment | 1 | 100% | Crafting: Expert | Hollow residue (Tier 4). Named creature material |
| Void-touched foundation | 1 | 50% | Arcana: Expert + Crafting: Expert | Gems & crystals + Hollow residue (Tier 4). A piece of whatever the Architect was building at its core. The most valuable research material in the game. What was it making? |

---

## Natural Creatures

> The world of Aethos was dangerous before the Sundering. These creatures predate the Hollow and inhabit the regions players will explore.

### Greyvale & Farmlands — Tier 1

---

#### Grey Wolf — Beast, Tier 1

**Level:** 1 | **HP:** 11 | **AC:** 12 | **Speed:** 40 ft
**STR** 12 (+1) **DEX** 14 (+2) **CON** 12 (+1) **INT** 3 (-4) **WIS** 12 (+1) **CHA** 6 (-2)
**Save Prof:** DEX, WIS | **XP:** 25

**Attacks:**
| Name | Type | Reach | Hit | Damage | Special |
|---|---|---|---|---|---|
| Bite | Melee | 5 ft | +4 | 1d6+2 piercing | DC 11 STR save or knocked prone |

**Passives:** Pack Tactics (advantage if ally within 5 ft of target). Keen Hearing and Smell (advantage on related Perception).
**Behavior:** Packs surround prey. Target prone creatures. Retreat if alpha falls.
**Morale:** Flees at half pack size. | **Group:** Pack of 3-6
**Found in:** Greyvale forest, Thornveld edge, Drathian Steppe, mountain foothills

**Loot:**
| Drop | Qty | Chance | Requires |
|---|---|---|---|
| Wolf pelt | 1 | 100% | Survival: Trained |
| Wolf fangs | 1d4 | 100% | None |
| Wolf meat | 2 | 100% | Survival: Trained |

---

#### Wild Boar — Beast, Tier 1

**Level:** 1 | **HP:** 14 | **AC:** 11 | **Speed:** 30 ft
**STR** 14 (+2) **DEX** 10 (+0) **CON** 14 (+2) **INT** 2 (-4) **WIS** 10 (+0) **CHA** 4 (-3)
**Save Prof:** CON | **XP:** 25

**Attacks:**
| Name | Type | Reach | Hit | Damage | Special |
|---|---|---|---|---|---|
| Tusk | Melee | 5 ft | +4 | 1d6+2 slashing | If charged 15+ ft before attack: +1d6 damage |

**Passives:** Relentless (1/day, if reduced to 0 HP by an attack dealing 7 or less damage, drop to 1 HP instead). Charge (bonus damage on movement, see attack).
**Behavior:** Territorial. Charges at intruders. Does not pursue beyond territory.
**Morale:** Fights to death defending territory. Flees if encountered outside territory. | **Group:** Solitary or sounder of 2-4
**Found in:** Greyvale farmlands, forest edges, Thornveld outer

**Loot:**
| Drop | Qty | Chance | Requires |
|---|---|---|---|
| Boar hide | 1 | 100% | Survival: Trained |
| Boar tusks | 2 | 100% | None |
| Boar meat | 4 | 100% | Survival: Trained |

---

#### Giant Spider — Beast, Tier 1

**Level:** 2 | **HP:** 18 | **AC:** 13 | **Speed:** 30 ft (climb 30 ft)
**STR** 12 (+1) **DEX** 16 (+3) **CON** 12 (+1) **INT** 2 (-4) **WIS** 11 (+0) **CHA** 4 (-3)
**Save Prof:** DEX | **XP:** 50

**Attacks:**
| Name | Type | Reach | Hit | Damage | Special |
|---|---|---|---|---|---|
| Bite | Melee | 5 ft | +5 | 1d8+3 piercing | DC 12 CON save or Poisoned 1 hour + 1d6 poison damage |
| Web | Ranged | 30 ft | +5 | — | Target Restrained (STR DC 12 or slash through, AC 10, 5 HP) |

**Passives:** Spider Climb (climb surfaces including ceilings). Web Sense (knows location of any creature touching its web). Darkvision 60 ft.
**Behavior:** Ambush predator. Webs exits, waits on ceiling, drops on webbed prey. Retreats to web if threatened in open.
**Morale:** Flees if web is destroyed. | **Group:** Solitary or pair (shared web)
**Found in:** Greyvale ruins, caves, dungeons, Thornveld canopy

**Loot:**
| Drop | Qty | Chance | Requires |
|---|---|---|---|
| Spider silk | 1d4 | 75% | Survival: Trained |
| Venom sac | 1 | 50% | Survival: Expert |
| Spider chitin | 1d4 | 100% | None |

---

#### Bandit — Humanoid, Tier 1

**Level:** 2 | **HP:** 16 | **AC:** 13 (leather + DEX) | **Speed:** 30 ft
**STR** 12 (+1) **DEX** 14 (+2) **CON** 12 (+1) **INT** 10 (+0) **WIS** 10 (+0) **CHA** 10 (+0)
**Save Prof:** DEX | **XP:** 50

**Attacks:**
| Name | Type | Reach | Hit | Damage | Special |
|---|---|---|---|---|---|
| Short Sword | Melee | 5 ft | +4 | 1d6+2 slashing | — |
| Light Crossbow | Ranged | 80 ft | +4 | 1d8+2 piercing | — |

**Passives:** None.
**Actives:** Dirty Fighting (1/encounter) — throw dirt/sand: target Blinded 1 round (DEX save DC 12).
**Behavior:** Ambush from cover. Focus downed targets. Demand surrender before attacking if outnumbered.
**Morale:** Flees at half HP or if leader falls. Surrenders if clearly outmatched. | **Group:** Gang of 3-6, often with 1 Bandit Captain (Tier 2)
**Found in:** Roads between settlements, forest ambush points, ruins

**Loot:**
| Drop | Qty | Chance | Requires |
|---|---|---|---|
| Coin pouch | 2d6 sp | 100% | None |
| Leather armor (worn) | 1 | 50% | None |
| Short sword | 1 | 75% | None |
| Stolen goods | varies | 50% | None |

---

### Thornveld & Deep Forest — Tier 1-2

---

#### Thornveld Stalker — Beast, Tier 1

**Level:** 2 | **HP:** 22 | **AC:** 14 | **Speed:** 40 ft (climb 20 ft)
**STR** 14 (+2) **DEX** 16 (+3) **CON** 12 (+1) **INT** 4 (-3) **WIS** 14 (+2) **CHA** 6 (-2)
**Save Prof:** DEX, WIS | **XP:** 50

**Attacks:**
| Name | Type | Reach | Hit | Damage | Special |
|---|---|---|---|---|---|
| Claw | Melee | 5 ft | +5 | 1d6+3 slashing | — |
| Pounce | Melee | 5 ft | +5 | 1d8+3 slashing | Requires 20 ft movement. Target DEX save DC 13 or knocked prone. If prone: free bite attack (1d6+3) |

**Passives:** Keen Smell (advantage Perception by smell). Forest Camouflage (advantage Stealth in forest terrain).
**Behavior:** Ambush predator. Stalks from trees, pounces on isolated targets. Will not attack groups of 4+.
**Morale:** Flees if first pounce fails. | **Group:** Solitary
**Found in:** Thornveld, deep Greyvale forest

**Loot:**
| Drop | Qty | Chance | Requires |
|---|---|---|---|
| Stalker pelt | 1 | 100% | Survival: Trained |
| Stalker claws | 2 | 100% | None |

---

#### Corrupted Treant — Elemental, Tier 2

**Level:** 6 | **HP:** 55 | **AC:** 14 (bark) | **Speed:** 20 ft
**STR** 18 (+4) **DEX** 6 (-2) **CON** 16 (+3) **INT** 8 (-1) **WIS** 14 (+2) **CHA** 8 (-1)
**Save Prof:** STR, CON | **XP:** 200

**Attacks:**
| Name | Type | Reach | Hit | Damage | Special |
|---|---|---|---|---|---|
| Slam | Melee | 10 ft | +7 | 2d8+4 bludgeoning | Target pushed 10 ft |
| Thorn Barrage | Ranged | 30 ft (area) | DEX save DC 14 | 2d6 piercing | 15 ft cone. Half on success |

**Passives:** Vulnerability to fire (takes double damage). Resistance to bludgeoning and piercing. Rooted Aura — plants within 30 ft grow aggressively; area is difficult terrain.
**Actives:** Entangling Roots (Recharge 5-6) — all creatures within 15 ft: STR save DC 14 or Restrained. The ground erupts with roots.
**Behavior:** Territorial guardian of corrupted groves. A treant twisted by proximity to Hollow corruption — still natural, but warped and hostile. Prioritizes fire-users as threats.
**Morale:** Fights to death defending its grove. Will not pursue beyond 100 ft of its tree. | **Group:** Solitary (guarding 2-3 normal trees that are "its" grove)
**Found in:** Thornveld corruption edges, Greyvale where Hollow meets forest

**Loot:**
| Drop | Qty | Chance | Requires |
|---|---|---|---|
| Ironwood bark | 1d4 | 100% | Survival: Trained |
| Corrupted heartwood | 1 | 50% | Crafting: Expert |
| Thornveld amber | 1 | 25% | Survival: Expert |

---

### Drathian Steppe — Tier 1-2

---

#### Steppe Razorwing — Beast, Tier 1

**Level:** 2 | **HP:** 15 | **AC:** 13 | **Speed:** 10 ft, fly 60 ft
**STR** 10 (+0) **DEX** 16 (+3) **CON** 10 (+0) **INT** 3 (-4) **WIS** 14 (+2) **CHA** 6 (-2)
**Save Prof:** DEX | **XP:** 50

**Attacks:**
| Name | Type | Reach | Hit | Damage | Special |
|---|---|---|---|---|---|
| Talons | Melee | 5 ft | +5 | 1d6+3 slashing | On hit from a dive (30+ ft descent): +1d6 damage |
| Wing Slash | Melee | 5 ft | +5 | 1d4+3 slashing | Can target two adjacent creatures |

**Passives:** Flyby (doesn't provoke opportunity attacks when flying away). Keen Sight (advantage on Perception by sight).
**Behavior:** Dive-attacks from height. Targets small or isolated creatures. Retreats to altitude between attacks.
**Morale:** Flees after taking any damage (unless defending nest). | **Group:** Pair or flock of 4-8
**Found in:** Drathian Steppe, mountain passes, open highlands

**Loot:**
| Drop | Qty | Chance | Requires |
|---|---|---|---|
| Razorwing feathers | 1d6 | 100% | None |
| Razorwing talons | 2 | 75% | Survival: Trained |

---

#### Steppe Bison — Beast, Tier 1

**Level:** 2 | **HP:** 28 | **AC:** 11 | **Speed:** 40 ft
**STR** 18 (+4) **DEX** 8 (-1) **CON** 16 (+3) **INT** 2 (-4) **WIS** 10 (+0) **CHA** 4 (-3)
**Save Prof:** STR, CON | **XP:** 50

**Attacks:**
| Name | Type | Reach | Hit | Damage | Special |
|---|---|---|---|---|---|
| Gore | Melee | 5 ft | +6 | 2d6+4 piercing | If charged 20+ ft: target STR save DC 14 or knocked prone and Stunned 1 round |

**Passives:** Stampede — if 3+ bison charge in the same direction, all creatures in the path: DEX save DC 14 or 2d8 bludgeoning + prone.
**Behavior:** Herd animal. Normally docile. Panics and stampedes when threatened. Individual bison charge only when cornered or defending calves.
**Morale:** Stampedes away from danger. Individual fights to death only if cornered. | **Group:** Herd of 6-20 (only 1-2 fight; rest flee)
**Found in:** Drathian Steppe, open grasslands

**Loot:**
| Drop | Qty | Chance | Requires |
|---|---|---|---|
| Bison hide | 1 | 100% | Survival: Trained |
| Bison horn | 2 | 100% | None |
| Bison meat | 8 | 100% | Survival: Trained |

---

### Keldaran Mountains — Tier 1-3

---

#### Rock Viper — Beast, Tier 1

**Level:** 1 | **HP:** 6 | **AC:** 13 | **Speed:** 20 ft (climb 20 ft)
**STR** 4 (-3) **DEX** 16 (+3) **CON** 10 (+0) **INT** 1 (-5) **WIS** 10 (+0) **CHA** 2 (-4)
**Save Prof:** DEX | **XP:** 15

**Attacks:**
| Name | Type | Reach | Hit | Damage | Special |
|---|---|---|---|---|---|
| Bite | Melee | 5 ft | +5 | 1 piercing + 1d6 poison | DC 11 CON save or Poisoned 1 hour. Failed by 5+: Paralyzed 10 min |

**Passives:** Camouflage (advantage Stealth in rocky terrain). Tiny (can hide in cracks and crevices).
**Behavior:** Ambush. Hides in rocks, strikes exposed ankles or hands. Does not pursue.
**Morale:** Flees immediately after striking. | **Group:** Solitary or nest of 2-3
**Found in:** Keldaran Mountains, mountain passes, cave entrances

**Loot:**
| Drop | Qty | Chance | Requires |
|---|---|---|---|
| Viper venom | 1 dose | 75% | Survival: Expert |
| Viper skin | 1 | 50% | Survival: Trained |

---

#### Cave Wyrm — Beast, Tier 2

**Level:** 5 | **HP:** 52 | **AC:** 15 (scales) | **Speed:** 30 ft (climb 30 ft, burrow 10 ft)
**STR** 16 (+3) **DEX** 12 (+1) **CON** 16 (+3) **INT** 4 (-3) **WIS** 12 (+1) **CHA** 8 (-1)
**Save Prof:** STR, CON | **XP:** 150
**Multiattack:** 2 attacks — one Bite and one Tail

**Attacks:**
| Name | Type | Reach | Hit | Damage | Special |
|---|---|---|---|---|---|
| Bite | Melee | 5 ft | +6 | 1d10+3 piercing | On crit: target grappled (escape DC 14) |
| Tail Sweep | Melee | 10 ft | +6 | 1d8+3 bludgeoning | DEX save DC 14 or knocked prone. Reach 10 ft |
| Acid Spit | Ranged | 30 ft | +4 | 2d6 acid | Recharge 5-6. DEX save DC 13 for half. Corrodes metal armor (-1 AC until repaired) |

**Passives:** Tremorsense 30 ft (detects movement through ground). Darkvision 60 ft. Scales (resistance to acid damage).
**Behavior:** Ambush from tunnel walls or ceiling. Uses tremorsense to detect approaching prey. Fights aggressively — cave wyrms are always hungry.
**Morale:** Fights to 25% HP, then attempts to burrow and escape. | **Group:** Solitary or mated pair
**Found in:** Keldaran mines, mountain caves, underground passages

**Loot:**
| Drop | Qty | Chance | Requires |
|---|---|---|---|
| Wyrm scales | 1d6 | 100% | Survival: Trained |
| Wyrm acid gland | 1 | 50% | Survival: Expert |
| Wyrm teeth | 1d4 | 100% | None |
| Cave gemstones (from nest) | 1d4 | 25% | Investigation: Trained |

---

#### War Golem — Construct, Tier 3

**Level:** 10 | **HP:** 100 | **AC:** 18 (stone and steel) | **Speed:** 25 ft
**STR** 22 (+6) **DEX** 6 (-2) **CON** 20 (+5) **INT** 3 (-4) **WIS** 10 (+0) **CHA** 1 (-5)
**Save Prof:** STR, CON | **XP:** 500

**Attacks:**
| Name | Type | Reach | Hit | Damage | Special |
|---|---|---|---|---|---|
| Slam | Melee | 10 ft | +9 | 2d10+6 bludgeoning | Target pushed 10 ft |
| Stone Throw | Ranged | 60 ft | +9 | 2d8+6 bludgeoning | Throws chunks of itself. Each throw reduces max HP by 5 until repaired |

**Passives:** Damage Immunity (poison, psychic). Resistance (non-magical physical). Magic Resistance (advantage on saves vs spells). Immutable Form (immune to any effect that would alter its form).
**Behavior:** Follows last instructions given by its creator. Most Keldaran war golems guard ancient holds or mines. They do not communicate and cannot be reasoned with. They perform their duty until destroyed.
**Morale:** Fights to destruction. Cannot flee, surrender, or negotiate. | **Group:** Solitary (guarding a specific location)
**Found in:** Keldaran ancient holds, deep mines, ruins from the pre-Sundering era

**Loot:**
| Drop | Qty | Chance | Requires |
|---|---|---|---|
| Golem core | 1 | 100% | Crafting: Expert |
| Enchanted stone | 2d4 | 100% | None |
| Keldaran forged steel | 1d4 | 75% | Crafting: Trained |
| Power crystal | 1 | 25% | Arcana: Expert |

---

### Sunward Coast & Wetlands — Tier 1-2

---

#### Saltmarsh Lurker — Beast, Tier 1

**Level:** 2 | **HP:** 20 | **AC:** 12 | **Speed:** 20 ft, swim 40 ft
**STR** 14 (+2) **DEX** 12 (+1) **CON** 14 (+2) **INT** 2 (-4) **WIS** 10 (+0) **CHA** 4 (-3)
**Save Prof:** CON | **XP:** 50

**Attacks:**
| Name | Type | Reach | Hit | Damage | Special |
|---|---|---|---|---|---|
| Bite | Melee | 5 ft | +4 | 1d8+2 piercing | On hit: target grappled (escape DC 12). Grappled targets pulled underwater next turn |
| Tail Slap | Melee | 10 ft | +4 | 1d6+2 bludgeoning | Reach 10 ft |

**Passives:** Hold Breath (30 minutes). Ambush from Water (advantage on Stealth while submerged). Swamp Camouflage.
**Behavior:** Lies submerged near banks or fords. Grabs creatures at the water's edge and drags them under.
**Morale:** Releases prey if it takes 10+ damage in one hit. | **Group:** Solitary
**Found in:** Sunward Coast marshes, river crossings, wetlands

**Loot:**
| Drop | Qty | Chance | Requires |
|---|---|---|---|
| Lurker hide | 1 | 100% | Survival: Trained |
| Lurker teeth | 1d4 | 100% | None |

---

#### Tidecaller Eel — Beast, Tier 2

**Level:** 4 | **HP:** 35 | **AC:** 13 | **Speed:** 10 ft, swim 50 ft
**STR** 16 (+3) **DEX** 14 (+2) **CON** 14 (+2) **INT** 3 (-4) **WIS** 10 (+0) **CHA** 6 (-2)
**Save Prof:** DEX, CON | **XP:** 100

**Attacks:**
| Name | Type | Reach | Hit | Damage | Special |
|---|---|---|---|---|---|
| Bite | Melee | 10 ft | +6 | 1d10+3 piercing | Target grappled (escape DC 14) |
| Lightning Discharge | Area | 15 ft radius (water only) | CON save DC 13 | 2d8 lightning | All creatures in water within 15 ft. Recharge 5-6 |

**Passives:** Water Breathing. Electricity Absorption (immune to lightning; heals HP equal to lightning damage dealt to it). Keen Vibration Sense (detects movement in water, 60 ft).
**Behavior:** Territorial in coastal waters. Uses Lightning Discharge to stun prey, then bites grappled targets.
**Morale:** Retreats to deep water if outmatched on shore. | **Group:** Solitary or pair
**Found in:** Sunward Coast waters, river mouths, coastal caves

**Loot:**
| Drop | Qty | Chance | Requires |
|---|---|---|---|
| Eel skin | 1 | 100% | Survival: Trained |
| Lightning gland | 1 | 50% | Survival: Expert |
| Eel oil | 2 | 75% | Survival: Trained |

---

### Underground & Umbral Deep — Tier 2-3

---

#### Umbral Crawler — Beast, Tier 2

**Level:** 4 | **HP:** 32 | **AC:** 14 (chitin) | **Speed:** 30 ft (climb 30 ft)
**STR** 14 (+2) **DEX** 16 (+3) **CON** 12 (+1) **INT** 3 (-4) **WIS** 12 (+1) **CHA** 2 (-4)
**Save Prof:** DEX | **XP:** 100
**Multiattack:** 2 Claw attacks

**Attacks:**
| Name | Type | Reach | Hit | Damage | Special |
|---|---|---|---|---|---|
| Claw | Melee | 5 ft | +5 | 1d6+3 slashing | — |
| Mandible | Melee | 5 ft | +5 | 1d8+3 piercing | Only on grappled targets. Injects paralytic: DC 13 CON save or Paralyzed 1 minute |

**Passives:** Blindsight 60 ft (no eyes — hunts by vibration and scent). Sunlight Sensitivity (disadvantage in daylight). Pack Ambush (first attack from hidden has advantage and deals +1d6 damage).
**Behavior:** Hunts in packs in deep tunnels. Drops from ceilings. Targets weakest-looking creature. Uses paralytic on downed prey.
**Morale:** Flees if 50% of pack killed. | **Group:** Pack of 3-5
**Found in:** Umbral Deep, Keldaran deep mines, underground ruins

**Loot:**
| Drop | Qty | Chance | Requires |
|---|---|---|---|
| Crawler chitin | 1d4 | 100% | None |
| Paralytic gland | 1 | 50% | Survival: Expert |
| Crawler mandible | 2 | 75% | None |

---

#### Deepstone Guardian — Construct, Tier 2

**Level:** 5 | **HP:** 45 | **AC:** 16 (stone) | **Speed:** 20 ft
**STR** 18 (+4) **DEX** 8 (-1) **CON** 16 (+3) **INT** 6 (-2) **WIS** 10 (+0) **CHA** 4 (-3)
**Save Prof:** STR, CON | **XP:** 150

**Attacks:**
| Name | Type | Reach | Hit | Damage | Special |
|---|---|---|---|---|---|
| Stone Fist | Melee | 5 ft | +7 | 1d10+4 bludgeoning | — |
| Guardian Pulse | Area | 15 ft radius | CON save DC 14 | 1d8 force | Pushes all creatures 10 ft. Recharge 5-6 |

**Passives:** Damage Immunity (poison, psychic). Resistance (non-magical physical). Sentry Protocol — cannot be surprised. Detects all creatures within 30 ft even through walls (tremorsense).
**Actives:** Lockdown (1/encounter) — all doors/passages within 60 ft seal shut for 1 minute. STR DC 16 to force open.
**Behavior:** Guards ancient underground structures. Activates when intruders enter its zone. Will not pursue beyond its assigned area.
**Morale:** Fights to destruction within its zone. | **Group:** Solitary or pair (flanking a doorway)
**Found in:** Umbral Deep ruins, Keldaran ancient holds, pre-Sundering structures

**Loot:**
| Drop | Qty | Chance | Requires |
|---|---|---|---|
| Guardian core (small) | 1 | 100% | Crafting: Trained |
| Enchanted stone | 1d4 | 100% | None |
| Ancient mechanism | 1 | 25% | Crafting: Expert |

---

### Multi-Region Threats — Tier 2-3

---

#### Dire Bear — Beast, Tier 2

**Level:** 6 | **HP:** 60 | **AC:** 14 (thick hide) | **Speed:** 40 ft
**STR** 20 (+5) **DEX** 10 (+0) **CON** 18 (+4) **INT** 3 (-4) **WIS** 12 (+1) **CHA** 6 (-2)
**Save Prof:** STR, CON | **XP:** 200
**Multiattack:** 2 attacks — one Claw and one Bite

**Attacks:**
| Name | Type | Reach | Hit | Damage | Special |
|---|---|---|---|---|---|
| Claw | Melee | 10 ft | +8 | 1d8+5 slashing | Reach 10 ft |
| Bite | Melee | 5 ft | +8 | 2d6+5 piercing | On hit: target grappled (escape DC 16). Can only bite grappled targets on subsequent rounds |
| Maul (grappled target only) | Melee | 5 ft | auto-hit | 2d8+5 piercing | Only against grappled targets. The full-body crush |

**Passives:** Keen Smell (advantage Perception by smell). Thick Hide (resistance to cold damage). Territorial Rage — when below 25% HP: advantage on all attacks, +2 damage.
**Behavior:** Extremely territorial. Charges largest threat. Grapples and mauls. A dire bear in its rage state is one of the most dangerous natural encounters in the game.
**Morale:** Fights to death defending territory. Outside territory: retreats below 50% HP unless cubs nearby. | **Group:** Solitary or mother with 1-2 cubs (cubs are non-combatants)
**Found in:** Thornveld, Keldaran mountain forests, northern Greyvale

**Loot:**
| Drop | Qty | Chance | Requires |
|---|---|---|---|
| Dire bear hide | 1 | 100% | Survival: Trained |
| Dire bear claws | 4 | 100% | None |
| Dire bear heart | 1 | 75% | Survival: Expert |
| Dire bear fat | 2 | 100% | Survival: Trained |

---

#### Troll — Humanoid, Tier 2

**Level:** 6 | **HP:** 65 | **AC:** 13 | **Speed:** 30 ft
**STR** 18 (+4) **DEX** 12 (+1) **CON** 20 (+5) **INT** 6 (-2) **WIS** 8 (-1) **CHA** 6 (-2)
**Save Prof:** CON | **XP:** 200
**Multiattack:** 3 attacks — one Bite and two Claw

**Attacks:**
| Name | Type | Reach | Hit | Damage | Special |
|---|---|---|---|---|---|
| Claw | Melee | 5 ft | +7 | 1d6+4 slashing | — |
| Bite | Melee | 5 ft | +7 | 1d8+4 piercing | — |

**Passives:** Regeneration (regain 5 HP start of each turn. Stops for 1 round if troll takes fire or acid damage). Keen Smell. Loathsome Limbs — severed limbs continue to act independently for 1 round (flavor only, no mechanical effect on combat math).
**Behavior:** Aggressive but dim. Charges in, attacks whatever is closest. Does not use tactics. Will switch targets if current target deals fire damage.
**Morale:** Fights while regenerating. Flees if on fire. | **Group:** Solitary or pair
**Found in:** Thornveld, mountain passes, marshes, ruins

**Loot:**
| Drop | Qty | Chance | Requires |
|---|---|---|---|
| Troll blood | 1d4 doses | 100% | Survival: Expert |
| Troll hide | 1 | 75% | Survival: Trained |
| Troll bone | 1d4 | 100% | None |

---

#### Bandit Captain — Humanoid, Tier 2

**Level:** 5 | **HP:** 45 | **AC:** 15 (chain shirt + DEX) | **Speed:** 30 ft
**STR** 14 (+2) **DEX** 16 (+3) **CON** 14 (+2) **INT** 12 (+1) **WIS** 12 (+1) **CHA** 14 (+2)
**Save Prof:** DEX, CHA | **XP:** 150
**Multiattack:** 2 attacks with Longsword or 2 Crossbow shots

**Attacks:**
| Name | Type | Reach | Hit | Damage | Special |
|---|---|---|---|---|---|
| Longsword | Melee | 5 ft | +6 | 1d8+3 slashing | — |
| Heavy Crossbow | Ranged | 100 ft | +6 | 1d10+3 piercing | — |

**Passives:** Leadership Aura — bandits within 30 ft gain +1 to attack rolls. Cunning Action — can Dash, Disengage, or Hide as a bonus action.
**Actives:** Rally (1/encounter) — all allied bandits within 30 ft regain 1d8 HP. Dirty Fighting (1/encounter) — advantage on next attack, and if it hits: target Blinded 1 round.
**Behavior:** Stays behind bodyguards. Uses crossbow at range, switches to sword when pressed. Commands bandits tactically — has them flank, focus fire, and retreat when losing.
**Morale:** Flees when last bodyguard falls. Surrenders if cornered and outmatched — will offer information or treasure for life. | **Group:** With 3-6 bandits
**Found in:** Roads, forest camps, ruins used as hideouts

**Loot:**
| Drop | Qty | Chance | Requires |
|---|---|---|---|
| Coin pouch | 4d6 sp + 1d6 gc | 100% | None |
| Chain shirt | 1 | 100% | None |
| Longsword (quality) | 1 | 100% | None |
| Stolen valuables | varies | 75% | None |
| Treasure map or intel | 1 | 25% | None |

---

#### Thunderbird — Beast, Tier 3

**Level:** 9 | **HP:** 90 | **AC:** 15 | **Speed:** 20 ft, fly 80 ft
**STR** 18 (+4) **DEX** 16 (+3) **CON** 16 (+3) **INT** 6 (-2) **WIS** 14 (+2) **CHA** 10 (+0)
**Save Prof:** DEX, CON | **XP:** 500
**Multiattack:** 2 attacks — one Beak and one Talons

**Attacks:**
| Name | Type | Reach | Hit | Damage | Special |
|---|---|---|---|---|---|
| Beak | Melee | 5 ft | +7 | 2d6+4 piercing | — |
| Talons | Melee | 5 ft | +7 | 1d8+4 slashing | Target grappled (escape DC 15). Thunderbird can fly while grappling — carries target |
| Lightning Breath | Area | 60 ft line | DEX save DC 15 | 4d8 lightning | Half on success. Recharge 5-6. The signature attack |

**Passives:** Flyby (no opportunity attacks when flying away). Lightning Absorption (immune to lightning; heals equal to lightning damage dealt to it). Storm Sense (knows when storms are coming within 6 hours; fights are more common during storms).
**Behavior:** Apex predator of mountain and steppe skies. Dives from extreme altitude, uses Lightning Breath on groups, picks up isolated targets with talons. Intelligent enough to avoid large armed groups.
**Morale:** Retreats to altitude if badly wounded. Returns when healed. Does not fight to the death unless defending nest. | **Group:** Solitary or mated pair
**Found in:** Keldaran mountain peaks, Drathian Steppe (during storms), high altitude everywhere

**Loot:**
| Drop | Qty | Chance | Requires |
|---|---|---|---|
| Thunderbird feathers | 2d6 | 100% | None |
| Lightning gland (large) | 1 | 75% | Survival: Expert |
| Thunderbird egg (if nest found) | 1 | 10% | None |
| Storm crystal | 1 | 25% | Arcana: Trained |

---

## Material Catalog Summary

### Material Categories

| Category | Source | Tiers | Crafts Into |
|---|---|---|---|
| Hides & pelts | Beasts | 1-3 | Leather armor, cloaks, bags, straps |
| Bones & teeth | Beasts, some Hollow | 1-3 | Weapons, tools, jewelry, arrowheads |
| Organs & fluids | Beasts (Expert harvest) | 1-4 | Potions, poisons, inks, alchemical reagents |
| Metals & stone | Gathering, purchase, constructs | 1-4 | Weapons, heavy armor, tools, structures |
| Wood & plant | Gathering, some creatures | 1-3 | Staves, bows, shields, building materials |
| Cloth & fiber | Purchase, gathering, humanoid drops | 1-3 | Robes, light armor, bandages, rope |
| Gems & crystals | Gathering, purchase, constructs | 2-4 | Enchantments, holy symbols, spell components |
| Hollow residue | Hollow creatures (Crafting: Expert) | 1-4 | Anti-Hollow weapons, Veil-ward components, research |
| Divine materials | Sacred sites, patron gifts, divine creatures | 2-4 | Blessed weapons, holy water, consecrated armor |
| Arcane components | Magical creatures, arcane sites, purchase | 2-4 | Scrolls, wands, enchanted items, spell ink |

### Hollow Residue Tiers

| Tier | Source | Material | Uses |
|---|---|---|---|
| 1 | Drift (Shadeling) | Drift residue | Detection ink, basic Veil-ward fuel, research samples |
| 2 | Rend (Mawling, Weaver) | Rend shard, spatial residue, dissolution membrane, woven void fragment | Anti-Hollow weapon coating (3 uses), Veil-ward components, teleportation research |
| 3 | Wrack (Hollowed Knight, Veilrender) | Wrack core, corrupted armor, Veil shard | Anti-Hollow weapons (permanent), Veil-ward anchors, priceless research |
| 4 | Named (Choir, Still, Architect) | Named fragment, choir resonance crystal, shard of false paradise, architect's blueprint, living stone | Supreme-tier crafting, legendary enchantments, world-altering research |

### Harvesting Skill Requirements

| Requirement | What You Can Harvest |
|---|---|
| None | Obvious items (coins, fangs, dropped weapons, loose materials) |
| Survival: Trained | Pelts, meat, basic organs, common plant materials |
| Survival: Expert | Venom sacs, intact glands, rare organs, volatile materials |
| Crafting: Trained | Crafting-grade materials from constructs, identify salvageable components |
| Crafting: Expert | Hollow residue, delicate/volatile materials, purification assessment |
| Arcana: Trained | Magical components from magical creatures, identify enchanted materials |
| Arcana: Expert | Named creature fragments, high-tier arcane components, Veil shards |

### Tainted Material Rules

All Hollow-sourced materials are **tainted by default**:
- Using tainted materials in crafting creates items that function but carry corruption risk: passive Resonance generation (+1 per encounter while equipped), Hollow-attracting aura (encounters with Hollow creatures become 25% more frequent), or slow item degradation (loses 1 durability per session)
- **Purification** requires Dispel Corruption (Cleric spell, 3 Focus) or Artificer purification process (3 async Training cycles)
- **Purified Hollow materials** are among the most valuable in the game: Anti-Hollow weapons (bonus damage vs Hollow), Veil-ward components, research materials

---

## Encounter Building Guidelines

### Solo Player Scaling

Divine Ruin is designed for solo play (Phase 1) with a companion NPC. Encounters should be scaled for 1 player + 1 companion:

| Player Level | Standard Encounter | Tough Encounter | Boss Encounter |
|---|---|---|---|
| 1-2 | 2-3 Tier 1 creatures | 4-5 Tier 1 creatures | 1 Tier 2 creature |
| 3-4 | 1 Tier 2 creature | 1 Tier 2 + 2 Tier 1 | 1 Tier 2 (elite variant) |
| 5-8 | 1 Tier 2 + 2-3 Tier 1 | 2 Tier 2 creatures | 1 Tier 3 creature |
| 9-14 | 1 Tier 3 creature | 1 Tier 3 + 2 Tier 2 | 1 Tier 3 (elite) + Tier 2 adds |
| 15-20 | 1 Tier 3 + Tier 2 adds | 2 Tier 3 creatures | 1 Tier 4 creature |

### Companion Scaling

The companion NPC should be approximately 75% of the player's combat effectiveness. This means the player + companion together are roughly 1.75× a single character. Encounters balanced for 2 full characters would be too easy; encounters for 1 would be too hard.

### Environment Modifiers

| Condition | Effect on Encounter |
|---|---|
| Hollow corruption (light) | All creatures gain +1 Resonance generation. Drift-tier Hollow may wander into fight |
| Hollow corruption (heavy) | +2 Resonance generation. Rend-tier Hollow reinforcements possible |
| Natural terrain (Druid/Warden home) | Primal casters gain advantage on terrain-related spells. Resonance reduced |
| Urban/indoor | Primal casters lose terrain bonuses. Enclosed spaces favor area denial |
| Night | Nocturnal creatures gain advantage. Hollow creatures more active |
| Sacred site | Veil locally stabilized. All Resonance halved. Hollow creatures at disadvantage |

---

## Design Decisions Log (Bestiary)

> **Extracted to `game_mechanics_decisions.md`.** Decisions 24-29 cover the bestiary and material systems.
